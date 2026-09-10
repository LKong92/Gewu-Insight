# Authenticode release helpers. These do not change Windows trust or policy.
$ErrorActionPreference = 'Stop'

function Assert-GewuRsaSignature {
    param([Parameter(Mandatory)]$Signature, [Parameter(Mandatory)][string]$Path,
          [switch]$RequireTimestamp)
    if ($Signature.Status -ne 'Valid') {
        throw "Signature verification failed ($($Signature.Status)): $Path"
    }
    if ($Signature.SignerCertificate.PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1') {
        throw "Smart App Control release signing requires an RSA certificate: $Path"
    }
    if ($RequireTimestamp -and -not $Signature.TimeStamperCertificate) {
        throw "The new signature has no verified timestamp: $Path"
    }
}

function Resolve-GewuSigningConfiguration {
    param([Parameter(Mandatory)][string]$Path)
    $config = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($config.Mode -notin 'CertificateStore', 'ArtifactSigning') {
        throw 'Signing Mode must be CertificateStore or ArtifactSigning.'
    }
    $config.SignTool = (Get-Item -LiteralPath $config.SignTool -ErrorAction Stop).FullName
    $toolSignature = Get-AuthenticodeSignature -LiteralPath $config.SignTool
    Assert-GewuRsaSignature $toolSignature $config.SignTool
    if ($toolSignature.SignerCertificate.GetNameInfo('SimpleName', $false) -ne 'Microsoft Corporation') {
        throw 'Use Microsoft Windows SDK SignTool.'
    }
    if ($config.Mode -eq 'CertificateStore') {
        if ($config.Thumbprint -notmatch '\A[0-9a-fA-F]{40}\z') {
            throw 'Provide the exact thumbprint of the publisher code-signing certificate.'
        }
        $certificate = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $config.Thumbprint) -ErrorAction Stop
        if (-not $certificate.HasPrivateKey -or $certificate.NotBefore -gt (Get-Date) -or $certificate.NotAfter -le (Get-Date)) {
            throw 'The selected signing certificate needs a usable private key and current validity.'
        }
        if ($certificate.PublicKey.Oid.Value -ne '1.2.840.113549.1.1.1' -or
            $certificate.Subject -eq $certificate.Issuer -or
            '1.3.6.1.5.5.7.3.3' -notin @($certificate.EnhancedKeyUsageList.ObjectId)) {
            throw 'Use an RSA code-signing certificate from a trusted certificate provider.'
        }
        $chain = [Security.Cryptography.X509Certificates.X509Chain]::new()
        try {
            $chain.ChainPolicy.RevocationMode = 'Online'
            $chain.ChainPolicy.ApplicationPolicy.Add([Security.Cryptography.Oid]::new('1.3.6.1.5.5.7.3.3'))
            if (-not $chain.Build($certificate)) { throw 'The publisher certificate chain did not validate.' }
        } finally { $chain.Dispose() }
    } else {
        $config.Dlib = (Get-Item -LiteralPath $config.Dlib -ErrorAction Stop).FullName
        $dlibSignature = Get-AuthenticodeSignature -LiteralPath $config.Dlib
        Assert-GewuRsaSignature $dlibSignature $config.Dlib
        if ($dlibSignature.SignerCertificate.GetNameInfo('SimpleName', $false) -ne 'Microsoft Corporation') {
            throw 'Use the official Microsoft Artifact Signing client library.'
        }
        $config.Metadata = (Get-Item -LiteralPath $config.Metadata -ErrorAction Stop).FullName
        $metadata = Get-Content -LiteralPath $config.Metadata -Raw | ConvertFrom-Json
        $endpoint = [uri]$metadata.Endpoint
        if ($endpoint.Scheme -ne 'https' -or $endpoint.Host -notmatch '\A[a-z]+\.codesigning\.azure\.net\z' -or
            -not $endpoint.IsDefaultPort -or $endpoint.UserInfo -or $endpoint.Query -or $endpoint.Fragment -or
            $endpoint.AbsolutePath -ne '/' -or -not $metadata.CodeSigningAccountName -or -not $metadata.CertificateProfileName) {
            throw 'Provide a valid official Artifact Signing endpoint, account, and Public Trust profile.'
        }
    }
    return $config
}

function Invoke-GewuFileSigning {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)]$Configuration)
    $file = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($file.PSIsContainer -or ($file.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Sign only regular files: $Path"
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    if ($signature.Status -eq 'Valid') {
        # Preserve upstream publisher signatures and bytes.
        Assert-GewuRsaSignature $signature $file.FullName
        return
    }
    if ($signature.Status -ne 'NotSigned') {
        throw "Refusing to overwrite an invalid existing signature ($($signature.Status)): $Path"
    }
    $arguments = @('sign', '/fd', 'SHA256', '/tr', 'http://timestamp.acs.microsoft.com', '/td', 'SHA256')
    if ($Configuration.Mode -eq 'CertificateStore') {
        $arguments += @('/sha1', $Configuration.Thumbprint, '/s', 'My')
    } elseif ($Configuration.Mode -eq 'ArtifactSigning') {
        $arguments += @('/dlib', $Configuration.Dlib, '/dmdf', $Configuration.Metadata)
    } else { throw 'Unsupported signing configuration.' }
    & $Configuration.SignTool @arguments $file.FullName | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed: $Path" }
    $signature = Get-AuthenticodeSignature -LiteralPath $file.FullName
    Assert-GewuRsaSignature $signature $file.FullName -RequireTimestamp
    if ($Configuration.Mode -eq 'CertificateStore' -and
        $signature.SignerCertificate.Thumbprint -ne $Configuration.Thumbprint) {
        throw "Unexpected publisher certificate: $Path"
    }
    & $Configuration.SignTool verify /pa /all $file.FullName | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "SignTool verification failed: $Path" }
}

function Test-GewuPayloadSignatures {
    param([Parameter(Mandatory)][string]$Path, [string]$ReportPath, [switch]$RequireTrusted)
    $root = (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
    $entries = @(Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Extension -in '.exe', '.dll', '.pyd' } | ForEach-Object {
            if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected linked binary: $($_.FullName)" }
            $signature = Get-AuthenticodeSignature -LiteralPath $_.FullName
            $rsa = $signature.SignerCertificate -and $signature.SignerCertificate.PublicKey.Oid.Value -eq '1.2.840.113549.1.1.1'
            [pscustomobject]@{
                Path = [IO.Path]::GetRelativePath($root, $_.FullName)
                Status = $signature.Status.ToString()
                Rsa = [bool]$rsa
                SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        })
    if (-not $entries.Count) { throw 'No release binaries found to verify.' }
    if ($ReportPath) { $entries | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ReportPath -Encoding utf8 }
    $failures = @($entries | Where-Object { $_.Status -ne 'Valid' -or -not $_.Rsa })
    if ($RequireTrusted -and $failures.Count) {
        throw "Installer blocked: $($failures.Count) of $($entries.Count) binaries lack a valid RSA signature. First: $($failures[0].Path)."
    }
    return [pscustomobject]@{Binaries=$entries.Count;ValidRsa=$entries.Count-$failures.Count;MissingOrInvalid=$failures.Count}
}

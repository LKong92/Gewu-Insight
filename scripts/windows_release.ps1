# Read-only release checks. Never launch the payload or change Windows trust.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows_signing.ps1')

function Assert-GewuPayloadManifest {
    param([Parameter(Mandatory)][string]$Path)
    $root = (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw 'Payload must be a directory.' }
    if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Payload must not be a link.'
    }
    $all = @(Get-ChildItem -LiteralPath $root -Recurse -Force -ErrorAction Stop)
    if (@($all | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
        throw 'Payload contains a linked file or directory.'
    }
    $manifestPath = Join-Path $root 'manifest.json'
    $entries = @(Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop | ConvertFrom-Json)
    if (-not $entries.Count) { throw 'Payload manifest is empty.' }
    $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $entries) {
        $relative = [string]$entry.Path
        $parts = $relative -split '[\\/]'
        if (-not $relative -or [IO.Path]::IsPathRooted($relative) -or
            $relative -match '[:*?"<>|\x00-\x1f]' -or
            @($parts | Where-Object { $_ -in '', '.', '..' -or $_ -match '[ .]$' }).Count) {
            throw "Unsafe manifest path: $relative"
        }
        $normalized = $parts -join [IO.Path]::DirectorySeparatorChar
        if ($normalized -eq 'manifest.json' -or -not $seen.Add($normalized)) {
            throw "Duplicate or self-referencing manifest path: $relative"
        }
        if ([string]$entry.SHA256 -notmatch '\A[0-9a-fA-F]{64}\z' -or
            [string]$entry.Bytes -notmatch '\A[0-9]+\z') {
            throw "Invalid manifest digest or size: $relative"
        }
        $file = Get-Item -LiteralPath (Join-Path $root $normalized) -ErrorAction Stop
        if ($file.PSIsContainer -or $file.Length -ne [long]$entry.Bytes -or
            (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne $entry.SHA256) {
            throw "Payload differs from its manifest: $relative"
        }
    }
    $files = @($all | Where-Object { -not $_.PSIsContainer -and $_.FullName -ne $manifestPath })
    foreach ($file in $files) {
        $relative = [IO.Path]::GetRelativePath($root, $file.FullName)
        if (-not $seen.Contains($relative)) { throw "Unlisted payload file: $relative" }
    }
    if ($files.Count -ne $seen.Count) { throw 'Payload file count differs from manifest.' }
    return [pscustomobject]@{Files=$files.Count;SHA256=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash}
}

function Test-GewuWindowsRelease {
    param([Parameter(Mandatory)][string]$PayloadPath,
          [Parameter(Mandatory)][string]$InstallerPath,
          [Parameter(Mandatory)][string]$Version)
    $issues = [Collections.Generic.List[string]]::new()
    $manifest = $null
    $signatures = $null
    $installerHash = $null
    $payload = $null
    $installer = $null
    $publisher = $null
    try {
        if ($Version -notmatch '\A[0-9]+\.[0-9]+\.[0-9]+\z') { throw 'Version must have the form major.minor.patch.' }
        $payload = (Get-Item -LiteralPath $PayloadPath -ErrorAction Stop).FullName
        $manifest = Assert-GewuPayloadManifest -Path $payload
        foreach ($name in @('Gewu Insight.exe', 'Gewu Insight.dll', 'service/python.exe',
                           'service/service_entry.py', 'service/app/paper_monitor/ui_server.py')) {
            if (-not (Test-Path -LiteralPath (Join-Path $payload $name) -PathType Leaf)) {
                throw "Required payload file is missing: $name"
            }
        }
        $dll = Join-Path $payload 'Gewu Insight.dll'
        $actualVersion = (Get-Item -LiteralPath $dll).VersionInfo.FileVersion
        if ($actualVersion -ne "$Version.0") { throw "Payload version mismatch: expected $Version.0, got $actualVersion" }
    } catch { $issues.Add($_.Exception.Message) }

    # Re-read real signatures; a cached JSON inventory is not evidence of trust.
    if ($payload -and (Test-Path -LiteralPath $payload -PathType Container)) {
        try {
            $signatures = Test-GewuPayloadSignatures -Path $payload
            if ($signatures.MissingOrInvalid) {
                $issues.Add("Payload has $($signatures.MissingOrInvalid) of $($signatures.Binaries) binaries without a valid RSA signature.")
            }
            foreach ($name in @('Gewu Insight.exe', 'Gewu Insight.dll')) {
                $file = Join-Path $payload $name
                $signature = Get-AuthenticodeSignature -LiteralPath $file
                Assert-GewuRsaSignature $signature $file -RequireTimestamp
                if ($publisher -and $publisher -ne $signature.SignerCertificate.Subject) {
                    throw 'Gewu executable and DLL have different signing publishers.'
                }
                $publisher = $signature.SignerCertificate.Subject
            }
        } catch { $issues.Add($_.Exception.Message) }
    }
    try {
        $installer = Get-Item -LiteralPath $InstallerPath -ErrorAction Stop
        if ($installer.PSIsContainer -or $installer.Extension -ne '.exe' -or
            ($installer.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Installer must be a regular EXE file.' }
        $installerHash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
        $signature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
        Assert-GewuRsaSignature $signature $installer.FullName -RequireTimestamp
        if (-not $publisher -or $signature.SignerCertificate.Subject -ne $publisher) {
            throw 'Installer and Gewu payload must have the same verified signing publisher.'
        }
        if ($installer.VersionInfo.ProductVersion -ne $Version) {
            throw "Installer version mismatch: expected $Version, got $($installer.VersionInfo.ProductVersion)"
        }
    } catch { $issues.Add($_.Exception.Message) }
    return [pscustomobject]@{
        Stage='static-release-preflight';CheckedAt=(Get-Date).ToUniversalTime().ToString('o')
        StaticChecksPassed=($issues.Count -eq 0);RuntimeValidated=$false
        Version=$Version;PayloadPath=$payload;Manifest=$manifest;Signatures=$signatures
        InstallerPath=$InstallerPath;InstallerSHA256=$installerHash;Publisher=$publisher
        Issues=@($issues.ToArray())
    }
}

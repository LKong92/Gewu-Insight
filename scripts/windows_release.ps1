# Read-only release checks. Never launch the payload or change Windows trust.
$ErrorActionPreference = 'Stop'

function Assert-GewuOfficialDependency {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Publisher)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notlike "CN=$Publisher,*") {
        throw "Official dependency verification failed: $Path (expected $Publisher)."
    }
}

function Assert-GewuWebView2Bootstrapper {
    param([Parameter(Mandatory)][string]$Path)
    $file = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($file.PSIsContainer -or $file.Extension -ne '.exe' -or
        ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
        $file.Length -le 0 -or $file.Length -gt 10MB) {
        throw 'Expected the small WebView2 Evergreen Bootstrapper EXE, not the offline runtime installer.'
    }
    Assert-GewuOfficialDependency -Path $file.FullName -Publisher 'Microsoft Corporation'
}

function Test-GewuPayloadSignatures {
    param([Parameter(Mandatory)][string]$Path, [string]$ReportPath)
    $root = (Get-Item -LiteralPath $Path -ErrorAction Stop).FullName
    $entries = @(Get-ChildItem -LiteralPath $root -Recurse -File -ErrorAction Stop |
        Where-Object { $_.Extension -in '.exe', '.dll', '.pyd' } | ForEach-Object {
            if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Unexpected linked binary: $($_.FullName)" }
            $signature = Get-AuthenticodeSignature -LiteralPath $_.FullName
            [pscustomobject]@{
                Path=[IO.Path]::GetRelativePath($root, $_.FullName);Status=[string]$signature.Status
                SHA256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        })
    if (-not $entries.Count) { throw 'No release binaries found to verify.' }
    if ($ReportPath) { $entries | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $ReportPath -Encoding utf8 }
    $invalid = @($entries | Where-Object { $_.Status -notin 'Valid', 'NotSigned' })
    if ($invalid.Count) { throw "Damaged or unverifiable binary signature: $($invalid[0].Path) ($($invalid[0].Status))." }
    return [pscustomobject]@{Binaries=$entries.Count;Signed=@($entries | Where-Object Status -eq 'Valid').Count;Unsigned=@($entries | Where-Object Status -eq 'NotSigned').Count}
}

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
          [Parameter(Mandatory)][string]$Version,
          [string]$WebView2Bootstrapper = '')
    $issues = [Collections.Generic.List[string]]::new()
    $manifest = $null
    $signatures = $null
    $installerHash = $null
    $payload = $null
    $installer = $null
    $webviewHash = $null
    $installerSignature = $null
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
            Assert-GewuOfficialDependency -Path (Join-Path $payload 'service/python.exe') -Publisher 'Python Software Foundation'
        } catch { $issues.Add($_.Exception.Message) }
    }
    try {
        if (-not $WebView2Bootstrapper) { throw 'Setup needs its verified WebView2 Evergreen Bootstrapper input.' }
        Assert-GewuWebView2Bootstrapper -Path $WebView2Bootstrapper
        $webviewHash = (Get-FileHash -LiteralPath $WebView2Bootstrapper -Algorithm SHA256).Hash
    } catch { $issues.Add($_.Exception.Message) }
    try {
        $installer = Get-Item -LiteralPath $InstallerPath -ErrorAction Stop
        if ($installer.PSIsContainer -or $installer.Extension -ne '.exe' -or
            ($installer.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Installer must be a regular EXE file.' }
        $installerHash = (Get-FileHash -LiteralPath $installer.FullName -Algorithm SHA256).Hash
        $installerSignature = [string](Get-AuthenticodeSignature -LiteralPath $installer.FullName).Status
        if ($installerSignature -ne 'NotSigned') { throw "Expected intentionally unsigned Setup; got $installerSignature." }
        if ($installer.VersionInfo.ProductVersion.Trim() -ne $Version) {
            throw "Installer version mismatch: expected $Version, got $($installer.VersionInfo.ProductVersion)"
        }
    } catch { $issues.Add($_.Exception.Message) }
    return [pscustomobject]@{
        Stage='static-release-preflight';Distribution='unsigned';CheckedAt=(Get-Date).ToUniversalTime().ToString('o')
        StaticChecksPassed=($issues.Count -eq 0);RuntimeValidated=$false
        Version=$Version;PayloadPath=$payload;Manifest=$manifest;Signatures=$signatures
        InstallerPath=$InstallerPath;InstallerSHA256=$installerHash;InstallerSignature=$installerSignature
        WebView2Deployment='evergreen-online-if-missing';WebView2BootstrapperSHA256=$webviewHash;Installed=$false
        Issues=@($issues.ToArray())
    }
}

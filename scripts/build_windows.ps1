param(
    [string]$Python = '.venv/Scripts/python.exe',
    [string]$Dotnet = 'dotnet',
    [Parameter(Mandatory=$true)][string]$PythonRuntime,
    [string]$InnoCompiler = '',
    [string]$Version = '0.1.0',
    [string]$SigningConfiguration = ''
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repoRoot
. (Join-Path $PSScriptRoot 'windows_signing.ps1')
if ($InnoCompiler -and -not $SigningConfiguration) {
    throw 'Installer builds require a publisher signing configuration. See docs/WINDOWS_SIGNING.md.'
}
$signing = $null
if ($SigningConfiguration) {
    $SigningConfiguration = (Get-Item -LiteralPath $SigningConfiguration -ErrorAction Stop).FullName
    $signing = Resolve-GewuSigningConfiguration -Path $SigningConfiguration
}
$payload = Join-Path $repoRoot "dist/windows-preview-$Version"
if (Test-Path -LiteralPath $payload) {
    throw 'Use a new version or a fresh payload directory; this builder never deletes or merges an existing payload.'
}
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
$runtimeSignature = Get-AuthenticodeSignature -LiteralPath (Join-Path $PythonRuntime 'python.exe')
if ($runtimeSignature.Status -ne 'Valid' -or $runtimeSignature.SignerCertificate.Subject -notlike 'CN=Python Software Foundation,*') { throw 'Expected an official signed CPython embedded runtime' }
& $Dotnet publish windows/GewuInsight.Windows.csproj -c Release -r win-x64 --self-contained true -p:Version=$Version -o $payload --nologo
if ($LASTEXITCODE -ne 0) { throw 'Windows shell publishing failed' }
& $Python scripts/package_windows_service.py --runtime $PythonRuntime --output (Join-Path $payload 'service')
if ($LASTEXITCODE -ne 0) { throw 'Python service packaging failed' }
Copy-Item -LiteralPath (Join-Path $repoRoot 'windows/PREVIEW.txt') -Destination $payload
foreach ($guide in @('Windows_Preview_Guide.html', 'Windows_Preview_Guide.pdf')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot ('windows/' + $guide)) -Destination $payload
}
if ($signing) {
    Get-ChildItem -LiteralPath $payload -File -Recurse | Where-Object { $_.Extension -in '.exe', '.dll', '.pyd' } | ForEach-Object {
        Invoke-GewuFileSigning -Path $_.FullName -Configuration $signing
    }
}
Test-GewuPayloadSignatures -Path $payload -ReportPath (Join-Path $payload 'signature-report.json') -RequireTrusted:([bool]$signing) | Out-Host
# Generate hashes only after signing changes the binaries.
Get-ChildItem -LiteralPath $payload -File -Recurse | ForEach-Object {
    [PSCustomObject]@{Path = [IO.Path]::GetRelativePath($payload, $_.FullName); SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash; Bytes = $_.Length}
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding utf8
if ($InnoCompiler) {
    $powershellExe = (Get-Process -Id $PID).Path
    $signingScript = Join-Path $PSScriptRoot 'sign_windows_file.ps1'
    # Inno substitutes $q with a quote and $f with its quoted target filename.
    # Escape literal dollars in paths so Inno cannot interpret them as macros.
    $signCommand = '$q' + $powershellExe.Replace('$', '$$') + '$q -NoProfile -NonInteractive -File $q' +
        $signingScript.Replace('$', '$$') + '$q -ConfigurationPath $q' +
        $SigningConfiguration.Replace('$', '$$') + '$q -Path $f'
    & $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$(Join-Path $repoRoot 'dist/installers')" "/DAppVersion=$Version" "/Sgewu=$signCommand" windows/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
    $installerPath = Join-Path $repoRoot "dist/installers/Gewu-Insight-Windows-Preview-$Version-x64-Setup.exe"
    Assert-GewuRsaSignature (Get-AuthenticodeSignature -LiteralPath $installerPath) $installerPath -RequireTimestamp
}
if (-not $signing) { Write-Warning 'Unsigned development payload only; no installer was built or accepted for distribution.' }
Write-Output "Windows preview payload: $payload"

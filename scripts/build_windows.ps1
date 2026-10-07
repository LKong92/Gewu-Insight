param(
    [string]$Python = '.venv/Scripts/python.exe',
    [string]$Dotnet = 'dotnet',
    [Parameter(Mandatory=$true)][string]$PythonRuntime,
    [string]$InnoCompiler = '',
    [Parameter(Mandatory=$true)][string]$Version,
    [string]$WebView2Bootstrapper = '',
    [string]$ReuseServicePayload = '',
    [switch]$RebuildGuide
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repoRoot
. (Join-Path $PSScriptRoot 'windows_release.ps1')
if ($Version -notmatch '\A[0-9]+\.[0-9]+\.[0-9]+\z') { throw 'Version must have the form major.minor.patch.' }
if ($InnoCompiler -and -not $WebView2Bootstrapper) {
    throw 'Setup needs the official WebView2 Evergreen Bootstrapper.'
}
if ($WebView2Bootstrapper) {
    $WebView2Bootstrapper = (Get-Item -LiteralPath $WebView2Bootstrapper -ErrorAction Stop).FullName
    Assert-GewuWebView2Bootstrapper -Path $WebView2Bootstrapper
}
Assert-GewuOfficialDependency -Path (Join-Path $PythonRuntime 'python.exe') -Publisher 'Python Software Foundation'
$payload = Join-Path $repoRoot "dist/windows-trial-$Version"
if (Test-Path -LiteralPath $payload) {
    throw 'Use a new version or a fresh payload directory; this builder never deletes or merges an existing payload.'
}
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'
& $Dotnet publish windows/GewuInsight.Windows.csproj -c Release -r win-x64 --self-contained true -p:Version=$Version -o $payload --nologo
if ($LASTEXITCODE -ne 0) { throw 'Windows shell publishing failed' }
$assets = Get-Content -LiteralPath 'windows/obj/project.assets.json' -Raw | ConvertFrom-Json
$dependencies = Get-Content -LiteralPath (Join-Path $payload 'Gewu Insight.deps.json') -Raw | ConvertFrom-Json
foreach ($dependency in $dependencies.libraries.PSObject.Properties.Name) {
    if ($dependency -notmatch '^runtimepack\.' -and $dependency -notmatch '^Microsoft\.Web\.WebView2/') { continue }
    $packagePath = ($dependency -replace '^runtimepack\.', '').ToLowerInvariant()
    $package = $null
    foreach ($cache in $assets.packageFolders.PSObject.Properties.Name) {
        $candidate = Join-Path $cache $packagePath
        if (Test-Path -LiteralPath $candidate -PathType Container) { $package = $candidate; break }
    }
    if (-not $package) { throw "Runtime license package is missing: $dependency" }
    $notices = @(Get-ChildItem -LiteralPath $package -File | Where-Object { $_.Name -match '^(LICENSE|NOTICE|THIRD-PARTY-NOTICES)' })
    if (-not $notices.Count) { throw "Runtime license notices are missing: $dependency" }
    $destination = Join-Path $payload ('licenses/' + $packagePath)
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    $notices | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $destination }
}
$serviceArguments = @('scripts/package_windows_service.py', '--runtime', $PythonRuntime, '--output', (Join-Path $payload 'service'))
if ($ReuseServicePayload) {
    Assert-GewuPayloadManifest -Path $ReuseServicePayload | Out-Host
    $serviceArguments += @('--reuse-service', (Join-Path $ReuseServicePayload 'service'))
}
& $Python @serviceArguments
if ($LASTEXITCODE -ne 0) { throw 'Python service packaging failed' }
foreach ($notice in @('LICENSE', 'THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $notice) -Destination $payload
}
if ($RebuildGuide) {
    & $Python scripts/build_windows_preview_guide.py --version $Version
    if ($LASTEXITCODE -ne 0) { throw 'Windows User Guide generation failed' }
}
foreach ($guide in @('Windows_Preview_Guide.html', 'Windows_Preview_Guide.pdf')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot ('windows/' + $guide)) -Destination $payload
}
@"
Gewu Insight - Windows $Version

This complete desktop package includes Python, .NET and the application dependencies.
Start Gewu Insight.exe from the installed application folder or Start menu.
Setup uses an existing Microsoft WebView2 Runtime when available.
If WebView2 is missing, Setup downloads and installs it from Microsoft; internet access is required only for this step.

Windows may show a publisher warning or block execution. No security settings are changed by Setup.
User research data is stored separately from the application and is retained on uninstall.
Choose Help > User Guide for the searchable manual, with Print Guide inside it for the PDF edition.
"@ | Set-Content -LiteralPath (Join-Path $payload 'PREVIEW.txt') -Encoding utf8
Test-GewuPayloadSignatures -Path $payload -ReportPath (Join-Path $payload 'signature-report.json') | Out-Host
Get-ChildItem -LiteralPath $payload -File -Recurse | ForEach-Object {
    [PSCustomObject]@{Path = [IO.Path]::GetRelativePath($payload, $_.FullName); SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash; Bytes = $_.Length}
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding utf8
if ($InnoCompiler) {
    & $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$(Join-Path $repoRoot 'dist/installers')" "/DAppVersion=$Version" "/DWebView2Bootstrapper=$WebView2Bootstrapper" windows/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Unsigned installer build failed' }
    $installerPath = Join-Path $repoRoot "dist/installers/Gewu-Insight-Windows-$Version-x64-Setup.exe"
    & (Join-Path $PSScriptRoot 'test_windows_release.ps1') -PayloadPath $payload -InstallerPath $installerPath -Version $Version `
        -WebView2Bootstrapper $WebView2Bootstrapper -ReportPath (Join-Path $repoRoot "dist/installers/Gewu-Insight-Windows-$Version-preflight.json")
    Write-Output "Windows installer (not installed): $installerPath"
}
Write-Output "Complete Windows desktop payload: $payload"

param(
    [string]$Python = '.venv/Scripts/python.exe',
    [string]$Dotnet = 'dotnet',
    [Parameter(Mandatory=$true)][string]$PythonRuntime,
    [string]$InnoCompiler = '',
    [string]$Version = '0.1.0'
)
$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $repoRoot
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
Get-ChildItem -LiteralPath $payload -File -Recurse | ForEach-Object {
    [PSCustomObject]@{Path = [IO.Path]::GetRelativePath($payload, $_.FullName); SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash; Bytes = $_.Length}
} | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding utf8
if ($InnoCompiler) {
    & $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$(Join-Path $repoRoot 'dist/installers')" "/DAppVersion=$Version" windows/installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
}
Write-Output "Windows preview payload: $payload"

param(
    [Parameter(Mandatory)][string]$PayloadPath,
    [Parameter(Mandatory)][string]$InstallerPath,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$ReportPath,
    [string]$WebView2Bootstrapper = ''
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows_release.ps1')
$root = [IO.Path]::GetFullPath($PayloadPath).TrimEnd([IO.Path]::DirectorySeparatorChar)
$report = [IO.Path]::GetFullPath($ReportPath)
if ($report.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
    $report.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase) -or
    $report.Equals([IO.Path]::GetFullPath($InstallerPath), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Write the preflight report outside the release payload and installer.'
}
$result = Test-GewuWindowsRelease -PayloadPath $PayloadPath -InstallerPath $InstallerPath -Version $Version -WebView2Bootstrapper $WebView2Bootstrapper
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $report -Encoding utf8
$result | ConvertTo-Json -Depth 5
if (-not $result.StaticChecksPassed) {
    throw "Release preflight failed. Keep the current App running; do not start installation. See $report"
}

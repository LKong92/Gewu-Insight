$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $repo 'scripts/windows_release.ps1')
$fixture = Join-Path $repo ('tmp/release-preflight-' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $fixture 'payload'
New-Item -ItemType Directory -Path (Join-Path $payload 'nested') -Force | Out-Null
$file = Join-Path $payload 'nested/fixture.txt'
$manifestPath = Join-Path $payload 'manifest.json'
[IO.File]::WriteAllText($file, 'original fixture')
$entry = [pscustomobject]@{Path='nested/fixture.txt';Bytes=(Get-Item -LiteralPath $file).Length;SHA256=(Get-FileHash -LiteralPath $file).Hash}
function Write-Manifest($Entries) {
    ConvertTo-Json -InputObject @($Entries) -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8
}
$checks = [Collections.Generic.List[string]]::new()
function Expect-Rejection([string]$Name, [string]$Pattern) {
    $failure = $null
    try { Assert-GewuPayloadManifest -Path $payload | Out-Null } catch { $failure = $_.Exception.Message }
    if (-not $failure -or $failure -notlike $Pattern) { throw "$Name failed: $failure" }
    $checks.Add($Name)
}
Write-Manifest @($entry)
$valid = Assert-GewuPayloadManifest -Path $payload
if ($valid.Files -ne 1 -or $valid.SHA256 -ne (Get-FileHash -LiteralPath $manifestPath).Hash) { throw 'Valid manifest was not accepted.' }
$checks.Add('valid complete manifest accepted with exact digest')

[IO.File]::WriteAllText($file, 'modified fixture')
Expect-Rejection 'modified bytes rejected even with same length' 'Payload differs*'
[IO.File]::WriteAllText($file, 'original fixture')
foreach ($path in @('../outside.txt', 'C:/outside.txt', 'nested/../fixture.txt', 'nested/fixture.txt:stream', 'nested//fixture.txt', 'nested/fixture.txt.')) {
    $bad = [pscustomobject]@{Path=$path;Bytes=$entry.Bytes;SHA256=$entry.SHA256}
    Write-Manifest @($bad)
    Expect-Rejection "unsafe path rejected: $path" 'Unsafe manifest path*'
}
Write-Manifest @($entry,$entry)
Expect-Rejection 'duplicate paths rejected' 'Duplicate or self-referencing*'
$caseVariant = [pscustomobject]@{Path='NESTED/FIXTURE.TXT';Bytes=$entry.Bytes;SHA256=$entry.SHA256}
Write-Manifest @($entry,$caseVariant)
Expect-Rejection 'Windows case-insensitive duplicates rejected' 'Duplicate or self-referencing*'
Write-Manifest @([pscustomobject]@{Path='manifest.json';Bytes=0;SHA256=('0'*64)})
Expect-Rejection 'self-referencing manifest rejected' 'Duplicate or self-referencing*'
Write-Manifest @([pscustomobject]@{Path=$entry.Path;Bytes=$entry.Bytes;SHA256='bad'})
Expect-Rejection 'malformed digest rejected' 'Invalid manifest digest*'
Write-Manifest @([pscustomobject]@{Path=$entry.Path;Bytes=($entry.Bytes+1);SHA256=$entry.SHA256})
Expect-Rejection 'wrong byte count rejected' 'Payload differs*'
Write-Manifest @()
Expect-Rejection 'empty manifest rejected' 'Payload manifest is empty*'
Write-Manifest @($entry)
$extra = Join-Path $payload 'unexpected.txt'
[IO.File]::WriteAllText($extra, 'unexpected')
Expect-Rejection 'unlisted file rejected' 'Unlisted payload file*'
# Only this exact disposable fixture file is removed.
Remove-Item -LiteralPath $extra
$before = (Get-FileHash -LiteralPath $file).Hash
$result = Test-GewuWindowsRelease -PayloadPath $payload -InstallerPath (Join-Path $fixture 'missing.exe') -Version '0.1.20'
if ($result.StaticChecksPassed -or $result.RuntimeValidated -or $result.Issues.Count -lt 2 -or
    (Get-FileHash -LiteralPath $file).Hash -ne $before) { throw 'Incomplete release was accepted or changed.' }
$checks.Add('incomplete release reports blockers without running or changing payload')

# Do not let a diagnostic report overwrite the payload or installer.
$reportFailure = $null
try {
    & (Join-Path $repo 'scripts/test_windows_release.ps1') -PayloadPath $payload -InstallerPath $file -Version '0.1.20' -ReportPath $file | Out-Null
} catch { $reportFailure = $_.Exception.Message }
if ($reportFailure -notlike 'Write the preflight report outside*' -or (Get-FileHash -LiteralPath $file).Hash -ne $before) {
    throw 'Report location guard failed.'
}
$checks.Add('report cannot overwrite release files')

# Policy unit cases use synthetic signature/version metadata only in this test
# process. No certificate is created, trusted or used to sign a real binary.
foreach ($relative in @('Gewu Insight.exe','Gewu Insight.dll','service/python.exe',
                        'service/service_entry.py','service/app/paper_monitor/ui_server.py')) {
    $target = Join-Path $payload $relative
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
    [IO.File]::WriteAllText($target, 'inert test data; never executed')
}
$installerFile = Join-Path $fixture 'fixture-Setup.exe'
[IO.File]::WriteAllText($installerFile, 'inert installer fixture; never executed')
$entries = @(Get-ChildItem -LiteralPath $payload -File -Recurse | Where-Object { $_.FullName -ne $manifestPath } | ForEach-Object {
    [pscustomobject]@{Path=[IO.Path]::GetRelativePath($payload,$_.FullName);Bytes=$_.Length;SHA256=(Get-FileHash -LiteralPath $_.FullName).Hash}
})
Write-Manifest $entries
$script:fixtureSignatureStatus = 'NotSigned'
$script:fixturePythonStatus = 'Valid'
$script:fixturePythonPublisher = 'CN=Python Software Foundation, O=Python Software Foundation'
$script:fixtureWebViewStatus = 'Valid'
$script:fixtureWebViewPublisher = 'CN=Microsoft Corporation, O=Microsoft Corporation'
$script:fixtureWebViewBytes = 1000000
$script:fixtureInstallerStatus = 'NotSigned'
$script:fixtureDllVersion = '0.1.20.0'
$script:fixtureInstallerVersion = '0.1.20'
$webviewFile = Join-Path $fixture 'webview.exe'
[IO.File]::WriteAllText($webviewFile, 'inert official-runtime fixture; never executed')
function Get-Item {
    param([string]$LiteralPath, [string]$ErrorAction)
    $actual = Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -ErrorAction Stop
    if ($actual.Name -eq 'Gewu Insight.dll' -or $actual.FullName -eq $installerFile) {
        return [pscustomobject]@{FullName=$actual.FullName;PSIsContainer=$actual.PSIsContainer;
            Attributes=$actual.Attributes;Extension=$actual.Extension;Length=$actual.Length;
            VersionInfo=[pscustomobject]@{FileVersion=$script:fixtureDllVersion;ProductVersion=$script:fixtureInstallerVersion}}
    }
    if ($actual.FullName -eq $webviewFile) {
        return [pscustomobject]@{FullName=$actual.FullName;PSIsContainer=$actual.PSIsContainer;
            Attributes=$actual.Attributes;Extension=$actual.Extension;Length=$script:fixtureWebViewBytes}
    }
    return $actual
}
function Get-AuthenticodeSignature {
    param([string]$LiteralPath)
    $status = $script:fixtureSignatureStatus
    $subject = 'CN=Inert vendor, O=Inert vendor'
    if ([IO.Path]::GetFileName($LiteralPath) -eq 'python.exe') {
        $status = $script:fixturePythonStatus; $subject = $script:fixturePythonPublisher
    }
    if ($LiteralPath -eq $webviewFile) {
        $status = $script:fixtureWebViewStatus; $subject = $script:fixtureWebViewPublisher
    }
    if ($LiteralPath -eq $installerFile) { $status = $script:fixtureInstallerStatus }
    return [pscustomobject]@{Status=$status;SignerCertificate=[pscustomobject]@{Subject=$subject}}
}
function Check-ReleasePolicy([string]$Name, [string]$ExpectedIssue) {
    $result = Test-GewuWindowsRelease -PayloadPath $payload -InstallerPath $installerFile -Version '0.1.20' -WebView2Bootstrapper $webviewFile
    if ($ExpectedIssue) {
        if ($result.StaticChecksPassed -or -not @($result.Issues | Where-Object { $_ -like $ExpectedIssue }).Count) {
            throw "$Name failed: $($result | ConvertTo-Json -Depth 5 -Compress)"
        }
    } elseif (-not $result.StaticChecksPassed -or $result.RuntimeValidated -or $result.Installed -or $result.Distribution -ne 'unsigned' -or
        $result.WebView2Deployment -ne 'evergreen-online-if-missing' -or $result.WebView2BootstrapperSHA256 -ne (Get-FileHash -LiteralPath $webviewFile).Hash) {
        throw "$Name failed: $($result.Issues)"
    }
    $checks.Add($Name)
}
try {
    Check-ReleasePolicy 'unsigned app and Setup accepted without claiming startup or installation' ''
    $script:fixtureSignatureStatus = 'Valid'
    Check-ReleasePolicy 'existing vendor signatures accepted without re-signing' ''
    $script:fixtureSignatureStatus = 'HashMismatch'
    Check-ReleasePolicy 'damaged binary signatures rejected' '*Damaged or unverifiable binary signature*'
    $script:fixtureSignatureStatus = 'NotSigned'
    $script:fixturePythonStatus = 'NotSigned'
    Check-ReleasePolicy 'unverified Python runtime rejected' '*Official dependency verification failed*'
    $script:fixturePythonStatus = 'Valid'
    $script:fixturePythonPublisher = 'CN=Unexpected vendor, O=Unexpected vendor'
    Check-ReleasePolicy 'wrong Python publisher rejected' '*expected Python Software Foundation*'
    $script:fixturePythonPublisher = 'CN=Python Software Foundation, O=Python Software Foundation'
    $script:fixtureWebViewStatus = 'NotSigned'
    Check-ReleasePolicy 'unverified WebView2 input rejected' '*expected Microsoft Corporation*'
    $script:fixtureWebViewStatus = 'Valid'
    $script:fixtureWebViewBytes = 212358352
    Check-ReleasePolicy 'oversized offline runtime cannot replace the online bootstrapper' '*Expected the small WebView2 Evergreen Bootstrapper*'
    $script:fixtureWebViewBytes = 0
    Check-ReleasePolicy 'empty bootstrapper rejected' '*Expected the small WebView2 Evergreen Bootstrapper*'
    $script:fixtureWebViewBytes = 1000000
    $script:fixtureInstallerStatus = 'HashMismatch'
    Check-ReleasePolicy 'damaged installer signature rejected' '*Expected intentionally unsigned Setup*'
    $script:fixtureInstallerStatus = 'NotSigned'
    $script:fixtureInstallerVersion = '0.1.20                                            '
    Check-ReleasePolicy 'Inno padded product-version text accepted' ''
    $script:fixtureDllVersion = '0.1.19.0'
    Check-ReleasePolicy 'stale DLL version rejected' '*Payload version mismatch*'
    $script:fixtureDllVersion = '0.1.20.0'
    $script:fixtureInstallerVersion = '0.1.19'
    Check-ReleasePolicy 'stale installer version rejected' '*Installer version mismatch*'
} finally {
    Remove-Item Function:Get-Item,Function:Get-AuthenticodeSignature
}
$buildFailure = $null
try { & (Join-Path $repo 'scripts/build_windows.ps1') -Version 0.0.0 -PythonRuntime unused -InnoCompiler unused }
catch { $buildFailure = $_.Exception.Message }
if ($buildFailure -ne 'Setup needs the official WebView2 Evergreen Bootstrapper.') { throw 'Setup prerequisite guard failed.' }
$checks.Add('builder requires online bootstrapper before making output')
$report = [pscustomobject]@{Success=$true;Checks=@($checks.ToArray());Fixture=$fixture}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $fixture 'result.json') -Encoding utf8
$report | ConvertTo-Json -Depth 4

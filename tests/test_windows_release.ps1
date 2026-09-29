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
$script:fixtureSignatureStatus = 'Valid'
$script:fixtureRsa = $true
$script:fixtureTimestamp = $true
$script:fixturePublisher = 'CN=Inert unit test publisher'
$script:fixtureInstallerPublisher = $script:fixturePublisher
$script:fixtureDllPublisher = $script:fixturePublisher
$script:fixtureDllVersion = '0.1.20.0'
$script:fixtureInstallerVersion = '0.1.20'
function Get-Item {
    param([string]$LiteralPath, [string]$ErrorAction)
    $actual = Microsoft.PowerShell.Management\Get-Item -LiteralPath $LiteralPath -ErrorAction Stop
    if ($actual.Name -eq 'Gewu Insight.dll' -or $actual.FullName -eq $installerFile) {
        return [pscustomobject]@{FullName=$actual.FullName;PSIsContainer=$actual.PSIsContainer;
            Attributes=$actual.Attributes;Extension=$actual.Extension;Length=$actual.Length;
            VersionInfo=[pscustomobject]@{FileVersion=$script:fixtureDllVersion;ProductVersion=$script:fixtureInstallerVersion}}
    }
    return $actual
}
function Get-AuthenticodeSignature {
    param([string]$LiteralPath)
    $subject = $script:fixturePublisher
    if ([IO.Path]::GetFileName($LiteralPath) -eq 'Gewu Insight.dll') { $subject = $script:fixtureDllPublisher }
    if ($LiteralPath -eq $installerFile) { $subject = $script:fixtureInstallerPublisher }
    return [pscustomobject]@{Status=$script:fixtureSignatureStatus;
        SignerCertificate=[pscustomobject]@{Subject=$subject;PublicKey=[pscustomobject]@{
            Oid=[pscustomobject]@{Value=$(if ($script:fixtureRsa) {'1.2.840.113549.1.1.1'} else {'1.2.840.10045.2.1'})}}};
        TimeStamperCertificate=$(if ($script:fixtureTimestamp) {'inert timestamp metadata'} else {$null})}
}
function Check-ReleasePolicy([string]$Name, [string]$ExpectedIssue) {
    $result = Test-GewuWindowsRelease -PayloadPath $payload -InstallerPath $installerFile -Version '0.1.20'
    if ($ExpectedIssue) {
        if ($result.StaticChecksPassed -or -not @($result.Issues | Where-Object { $_ -like $ExpectedIssue }).Count) {
            throw "$Name failed: $($result | ConvertTo-Json -Depth 5 -Compress)"
        }
    } elseif (-not $result.StaticChecksPassed -or $result.RuntimeValidated) { throw "$Name failed: $($result.Issues)" }
    $checks.Add($Name)
}
try {
    Check-ReleasePolicy 'synthetic complete release passes static policy but never claims runtime acceptance' ''
    $script:fixtureSignatureStatus = 'NotSigned'
    Check-ReleasePolicy 'unsigned components and installer rejected by policy' '*without a valid RSA signature*'
    $script:fixtureSignatureStatus = 'HashMismatch'
    Check-ReleasePolicy 'damaged signatures rejected by policy' '*Signature verification failed (HashMismatch)*'
    $script:fixtureSignatureStatus = 'Valid'
    $script:fixtureRsa = $false
    Check-ReleasePolicy 'unsupported ECC signature rejected by policy' '*requires an RSA certificate*'
    $script:fixtureRsa = $true
    $script:fixtureTimestamp = $false
    Check-ReleasePolicy 'missing timestamp rejected by policy' '*no verified timestamp*'
    $script:fixtureTimestamp = $true
    $script:fixtureInstallerPublisher = 'CN=Different installer publisher'
    Check-ReleasePolicy 'different installer publisher rejected' '*same verified signing publisher*'
    $script:fixtureInstallerPublisher = $script:fixturePublisher
    $script:fixtureDllPublisher = 'CN=Different DLL publisher'
    Check-ReleasePolicy 'different Gewu DLL publisher rejected' '*different signing publishers*'
    $script:fixtureDllPublisher = $script:fixturePublisher
    $script:fixtureDllVersion = '0.1.19.0'
    Check-ReleasePolicy 'stale DLL version rejected' '*Payload version mismatch*'
    $script:fixtureDllVersion = '0.1.20.0'
    $script:fixtureInstallerVersion = '0.1.19'
    Check-ReleasePolicy 'stale installer version rejected' '*Installer version mismatch*'
} finally {
    Remove-Item Function:Get-Item,Function:Get-AuthenticodeSignature
}
$report = [pscustomobject]@{Success=$true;Checks=@($checks.ToArray());Fixture=$fixture}
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $fixture 'result.json') -Encoding utf8
$report | ConvertTo-Json -Depth 4

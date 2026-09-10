param(
    [Parameter(Mandatory)][string]$SignTool,
    [Parameter(Mandatory)][string]$InnoCompiler
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$SignTool = (Get-Item -LiteralPath $SignTool).FullName
$InnoCompiler = (Get-Item -LiteralPath $InnoCompiler).FullName
. (Join-Path $repo 'scripts/windows_signing.ps1')
$fixtureRoot = Join-Path $repo ('tmp/signing checks $literal ' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureRoot | Out-Null
$configuration = [pscustomobject]@{Mode='CertificateStore';SignTool=$SignTool;Thumbprint=('0' * 40)}
$configurationPath = Join-Path $fixtureRoot 'unavailable publisher.json'
$configuration | ConvertTo-Json | Set-Content -LiteralPath $configurationPath -Encoding utf8

try {
    Resolve-GewuSigningConfiguration -Path $configurationPath | Out-Null
    throw 'Missing publisher was accepted'
} catch {
    if ($_.Exception.Message -notlike '*Cert:\CurrentUser\My\0000*') { throw }
}

$signedCopy = Join-Path $fixtureRoot 'valid Microsoft tool.exe'
Copy-Item -LiteralPath $SignTool -Destination $signedCopy
$before = (Get-FileHash -LiteralPath $signedCopy).Hash
Invoke-GewuFileSigning -Path $signedCopy -Configuration $configuration
if ((Get-FileHash -LiteralPath $signedCopy).Hash -ne $before) { throw 'Vendor signature was modified' }

# Alter a local test copy only; never execute or distribute this damaged binary.
$tamperedCopy = Join-Path $fixtureRoot 'damaged signature fixture.exe'
Copy-Item -LiteralPath $SignTool -Destination $tamperedCopy
$stream = [IO.File]::Open($tamperedCopy, 'Open', 'ReadWrite', 'None')
try {
    $stream.Position = 64
    $originalByte = $stream.ReadByte()
    $stream.Position = 64
    $stream.WriteByte($originalByte -bxor 1)
} finally { $stream.Dispose() }
$tamperedHash = (Get-FileHash -LiteralPath $tamperedCopy).Hash
try {
    Invoke-GewuFileSigning -Path $tamperedCopy -Configuration $configuration
    throw 'Invalid signature was accepted'
} catch {
    if ($_.Exception.Message -notlike 'Refusing to overwrite an invalid existing signature*') { throw }
}
if ((Get-FileHash -LiteralPath $tamperedCopy).Hash -ne $tamperedHash) { throw 'Invalid signature was overwritten' }

$payload = Join-Path $fixtureRoot 'payload'
$installerOutput = Join-Path $fixtureRoot 'installer output'
New-Item -ItemType Directory -Path $payload,$installerOutput | Out-Null
'Isolated signing callback test only.' | Set-Content -LiteralPath (Join-Path $payload 'fixture.txt')
$shellPath = (Get-Process -Id $PID).Path
$scriptPath = Join-Path $repo 'scripts/sign_windows_file.ps1'
$signCommand = '$q' + $shellPath.Replace('$', '$$') + '$q -NoProfile -NonInteractive -File $q' +
    $scriptPath.Replace('$', '$$') + '$q -ConfigurationPath $q' +
    $configurationPath.Replace('$', '$$') + '$q -Path $f'
$compilerLog = Join-Path $fixtureRoot 'inno-signing-failure.log'
& $InnoCompiler "/DPayloadDir=$payload" "/DOutputDir=$installerOutput" /DAppVersion=0.0.0-signing-test "/Sgewu=$signCommand" (Join-Path $repo 'windows/installer.iss') *> $compilerLog
$compilerExit = $LASTEXITCODE
if ($compilerExit -eq 0) { throw 'Installer compiled despite unavailable publisher credential' }
$log = Get-Content -LiteralPath $compilerLog -Raw
if ($log -notmatch 'Cert:\\CurrentUser\\My\\0000') { throw "Signing callback did not reach the missing credential check. See $compilerLog" }
if (Get-ChildItem -LiteralPath $installerOutput -Filter '*Setup.exe') { throw 'Failed signing emitted a Setup executable' }
$result = [pscustomobject]@{
    MissingPublisherRejected=$true
    ValidVendorBytesPreserved=$true
    InvalidSignatureNotOverwritten=$true
    InnoCallbackWithSpacesAndDollars=$true
    SigningFailurePreventedInstaller=$true
    CompilerExit=$compilerExit
    FixtureRoot=$fixtureRoot
}
$result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $fixtureRoot 'result.json') -Encoding utf8
$result | ConvertTo-Json

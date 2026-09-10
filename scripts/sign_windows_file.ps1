param(
    [Parameter(Mandatory)][string]$ConfigurationPath,
    [Parameter(Mandatory)][string]$Path
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows_signing.ps1')
$configuration = Resolve-GewuSigningConfiguration -Path $ConfigurationPath
Invoke-GewuFileSigning -Path $Path -Configuration $configuration

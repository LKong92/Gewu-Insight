# Native Windows shortcut feasibility probe. Uses only a fresh scratch tree.
# It does not install an adapter or migrate a Library.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputRoot)
$ErrorActionPreference = 'Stop'
$gewuProbeRoot = [IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $gewuProbeRoot) { throw 'Use a new output directory; existing contents are never overwritten.' }
[IO.Directory]::CreateDirectory($gewuProbeRoot) | Out-Null
function Assert-ProbePath([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($gewuProbeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Probe path escaped its scratch directory.'
    }
}
function Set-ProbeShortcut([string]$LinkPath, [string]$TargetPath) {
    Assert-ProbePath $LinkPath
    Assert-ProbePath $TargetPath
    $shortcut = $gewuShell.CreateShortcut($LinkPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($TargetPath)
    $shortcut.Description = 'Gewu Windows migration synthetic fixture'
    $shortcut.Save()
}
$gewuShell = New-Object -ComObject WScript.Shell
$gewuChecks = [ordered]@{}
$gewuTarget = Join-Path $gewuProbeRoot '论文 sample, #1.md'
$gewuLinkA = Join-Path $gewuProbeRoot 'Library entry.lnk'
$gewuLinkB = Join-Path $gewuProbeRoot 'Space 研究 entry.lnk'
[IO.File]::WriteAllText($gewuTarget, '# Synthetic original')
Set-ProbeShortcut $gewuLinkA $gewuTarget
Set-ProbeShortcut $gewuLinkB $gewuTarget
$gewuChecks.two_entries_same_target = ($gewuShell.CreateShortcut($gewuLinkA).TargetPath -eq $gewuTarget) -and ($gewuShell.CreateShortcut($gewuLinkB).TargetPath -eq $gewuTarget)
$gewuChecks.unicode_space_comma_hash_roundtrip = [IO.File]::Exists($gewuShell.CreateShortcut($gewuLinkB).TargetPath)
$gewuReplacement = Join-Path $gewuProbeRoot 'replacement.md'
[IO.File]::WriteAllText($gewuReplacement, '# Synthetic annotated replacement')
Assert-ProbePath $gewuReplacement
Assert-ProbePath $gewuTarget
[IO.File]::Move($gewuReplacement, $gewuTarget, $true)
$gewuChecks.atomic_replacement_keeps_both_entries = ([IO.File]::ReadAllText($gewuShell.CreateShortcut($gewuLinkA).TargetPath) -eq '# Synthetic annotated replacement') -and ([IO.File]::ReadAllText($gewuShell.CreateShortcut($gewuLinkB).TargetPath) -eq '# Synthetic annotated replacement')
$gewuMoved = Join-Path $gewuProbeRoot '重命名 paper.md'
Assert-ProbePath $gewuMoved
[IO.File]::Move($gewuTarget, $gewuMoved)
$gewuChecks.missing_target_detectable = -not [IO.File]::Exists($gewuShell.CreateShortcut($gewuLinkA).TargetPath)
Set-ProbeShortcut $gewuLinkA $gewuMoved
Set-ProbeShortcut $gewuLinkB $gewuMoved
$gewuChecks.explicit_retarget_repairs_both_entries = [IO.File]::Exists($gewuShell.CreateShortcut($gewuLinkA).TargetPath) -and [IO.File]::Exists($gewuShell.CreateShortcut($gewuLinkB).TargetPath)
Assert-ProbePath $gewuLinkA
Remove-Item -LiteralPath $gewuLinkA
$gewuChecks.delete_entry_preserves_target_and_other_entry = [IO.File]::Exists($gewuMoved) -and [IO.File]::Exists($gewuLinkB)
$gewuResult = [ordered]@{
    checks = $gewuChecks
    passed = -not ($gewuChecks.Values -contains $false)
    limitations = @('No Explorer double-click or external-app UI acceptance', 'No cross-volume fixture', 'No database/placement lifecycle integration', 'No Recycle Bin/rollback acceptance', 'No name-collision policy implementation')
}
$gewuJson = $gewuResult | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $gewuProbeRoot 'result.json'), $gewuJson)
Write-Output $gewuJson
if (-not $gewuResult.passed) { exit 1 }

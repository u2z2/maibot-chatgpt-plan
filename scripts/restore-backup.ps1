param([Parameter(Mandatory=$true)][string]$Backup, [switch]$Apply)
$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path $PSScriptRoot -Parent
$releasePython = Join-Path $releaseRoot '.venv\Scripts\python.exe'
$restoreArgs = @('-m','maibot_chatgpt_plan.restore',$Backup)
if ($Apply) { $restoreArgs += '--apply' }
& $releasePython @restoreArgs
if ($LASTEXITCODE -ne 0) { throw 'Restore failed.' }

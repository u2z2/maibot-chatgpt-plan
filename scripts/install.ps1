$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path $PSScriptRoot -Parent
$venvPython = Join-Path $releaseRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv (Join-Path $releaseRoot '.venv')
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv (Join-Path $releaseRoot '.venv')
    } else { throw 'Install Python 3.11 or later, then run this script again.' }
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create a Python environment.' }
}
& $venvPython -m pip install $releaseRoot
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Installed. Run scripts\start.ps1 to open the setup page.'

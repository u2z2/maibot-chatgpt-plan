param([int]$Port = 8776, [string]$MaiBotConfig = '')
$ErrorActionPreference = 'Stop'
$releaseRoot = Split-Path $PSScriptRoot -Parent
$releasePython = Join-Path $releaseRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $releasePython)) { throw 'Run scripts\install.ps1 first.' }
try {
    $releaseStatus = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
    if ($releaseStatus.service -eq 'MaiBot ChatGPT Plan') {
        Start-Process "http://127.0.0.1:$Port/"
        exit 0
    }
    throw 'This port is used by another service. Choose a different -Port.'
} catch {
    if ($_.Exception.Message -match 'another service') { throw }
}
$releaseArgs = @('-m','maibot_chatgpt_plan','--port',"$Port",'--open-browser')
if ($MaiBotConfig) {
    if ($MaiBotConfig.Contains('"')) { throw 'Invalid configuration path.' }
    $releaseArgs += @('--maibot-config',('"' + $MaiBotConfig + '"'))
}
Start-Process -FilePath $releasePython -ArgumentList $releaseArgs -WorkingDirectory $releaseRoot -WindowStyle Hidden

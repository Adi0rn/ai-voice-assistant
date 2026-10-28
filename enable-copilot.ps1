$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$listener = Join-Path $PSScriptRoot 'copilot_hotkey.py'
if (!(Test-Path -LiteralPath $pythonw)) { throw 'Run setup.ps1 first.' }
& $python -B $listener --status
if ($LASTEXITCODE -eq 0) { exit 0 }
$process = Start-Process -FilePath $pythonw -ArgumentList @('-B', ('"' + $listener + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
Start-Sleep -Milliseconds 800
& $python -B $listener --status
if ($LASTEXITCODE -ne 0) { throw 'Listener did not start. Check work\copilot-status.json or run copilot_hotkey.py from a terminal.' }
Write-Host 'Press the Copilot button to open the voice assistant. Press Enter in its window to speak.'
Write-Host 'To undo, run disable-copilot.ps1. Enable again after restarting Windows.'

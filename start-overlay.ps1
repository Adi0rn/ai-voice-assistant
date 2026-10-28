$ErrorActionPreference = 'Stop'
$pythonw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$overlay = Join-Path $PSScriptRoot 'overlay.py'
if (!(Test-Path -LiteralPath $pythonw)) { throw 'Run setup.ps1 first.' }
Start-Process -FilePath $pythonw -ArgumentList @('-B', ('"' + $overlay + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden

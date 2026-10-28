$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -B (Join-Path $PSScriptRoot 'copilot_hotkey.py') --stop

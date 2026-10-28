$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$workPath = Join-Path $projectRoot 'work'
New-Item -ItemType Directory -Force -Path $workPath | Out-Null
# Keep installer temporary files and caches under this project.
$env:TEMP = $workPath
$env:TMP = $workPath
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $venvPython)) {
    python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.10+ and ensure python is on PATH.' }
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$manifest = Join-Path $projectRoot 'requirements-lock.txt'
if (!(Test-Path -LiteralPath $manifest)) { $manifest = Join-Path $projectRoot 'requirements.txt' }
& $venvPython -m pip --isolated --disable-pip-version-check install --no-cache-dir --only-binary=:all: -r $manifest
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access.' }
if (!(Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
    Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination (Join-Path $projectRoot '.env')
}
Write-Host 'Setup complete. Edit .env locally, then follow README.md.'

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path $python)) { $python = Join-Path $PSScriptRoot '../.venv/Scripts/python.exe' }
if (-not (Test-Path $python)) { throw 'Please create .venv and install requirements.txt first.' }
& $python -m uvicorn app:app --host 127.0.0.1 --port 4190

# Uruchamia Tramdispatch na Windows. W PowerShellu, w folderze projektu:  .\run.ps1
# Jeśli skrypty są zablokowane: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
  python -m venv .venv
  .\.venv\Scripts\pip install -e ".[dev]"
}
.\.venv\Scripts\python -m backend.app

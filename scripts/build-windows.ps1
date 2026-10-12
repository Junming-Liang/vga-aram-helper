# Maintainer-only. End users download the .exe and do not run this script.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
$Python = Join-Path $PWD '.venv-build\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    py -3.12 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $Python -m pip install --index-url https://pypi.org/simple --only-binary=:all: -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python scripts/build_windows.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python tests/windows_exe_smoke.py --exe dist/VGA-Aram-Helper.exe
exit $LASTEXITCODE

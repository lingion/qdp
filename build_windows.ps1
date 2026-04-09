$ErrorActionPreference = 'Stop'

$pythonBin = if ($env:QDP_PYTHON) {
  $env:QDP_PYTHON
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  'py -3'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  'python'
} else {
  throw 'qdp build error: neither py nor python is available on PATH'
}

$venvDir = '.venv-build'
Invoke-Expression "$pythonBin -m venv $venvDir"
. .\$venvDir\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
python -m pip install -e . --no-build-isolation
python -m PyInstaller --clean --noconfirm qdp.spec

if (Test-Path 'dist/qdp/qdp.exe') {
  & 'dist/qdp/qdp.exe' --help | Out-Null
  Write-Host 'qdp build complete: dist/qdp/qdp.exe'
} elseif (Test-Path 'dist/qdp/qdp') {
  & 'dist/qdp/qdp' --help | Out-Null
  Write-Host 'qdp build complete: dist/qdp/qdp'
} elseif (Test-Path 'dist/qdp.exe') {
  & 'dist/qdp.exe' --help | Out-Null
  Write-Host 'qdp build complete: dist/qdp.exe'
} elseif (Test-Path 'dist/qdp') {
  & 'dist/qdp' --help | Out-Null
  Write-Host 'qdp build complete: dist/qdp'
} else {
  throw 'qdp build error: expected dist artifact was not created'
}

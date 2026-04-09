@echo off
setlocal EnableExtensions

set "PYTHON_BIN="
if not "%QDP_PYTHON%"=="" set "PYTHON_BIN=%QDP_PYTHON%"
if "%PYTHON_BIN%"=="" (
  where py >nul 2>nul && set "PYTHON_BIN=py -3"
)
if "%PYTHON_BIN%"=="" (
  where python >nul 2>nul && set "PYTHON_BIN=python"
)
if "%PYTHON_BIN%"=="" (
  echo qdp build error: neither py nor python is available on PATH 1>&2
  exit /b 1
)

set "VENV_DIR=.venv-build"
%PYTHON_BIN% -m venv "%VENV_DIR%" || exit /b 1
call "%VENV_DIR%\Scripts\activate.bat" || exit /b 1
python -m pip install --upgrade pip setuptools wheel || exit /b 1
python -m pip install -r requirements.txt || exit /b 1
python -m pip install -r requirements-build.txt || exit /b 1
python -m pip install -e . --no-build-isolation || exit /b 1
python -m PyInstaller --clean --noconfirm qdp.spec || exit /b 1

if exist dist\qdp\qdp.exe (
  dist\qdp\qdp.exe --help >nul || exit /b 1
  echo qdp build complete: dist\qdp\qdp.exe
  exit /b 0
)

if exist dist\qdp\qdp (
  dist\qdp\qdp --help >nul || exit /b 1
  echo qdp build complete: dist\qdp\qdp
  exit /b 0
)

if exist dist\qdp.exe (
  dist\qdp.exe --help >nul || exit /b 1
  echo qdp build complete: dist\qdp.exe
  exit /b 0
)

if exist dist\qdp (
  dist\qdp --help >nul || exit /b 1
  echo qdp build complete: dist\qdp
  exit /b 0
)

echo qdp build error: expected dist\qdp\qdp(.exe) artifact was not created 1>&2
exit /b 1

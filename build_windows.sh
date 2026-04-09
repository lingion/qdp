#!/usr/bin/env bash
set -euo pipefail

pick_python() {
  if [[ -n "${QDP_PYTHON:-}" ]]; then
    printf '%s\n' "$QDP_PYTHON"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s\n' python
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' python3
    return 0
  fi
  echo 'qdp build error: neither python nor python3 is available on PATH' >&2
  return 1
}

PYTHON_BIN="$(pick_python)"
VENV_DIR="${QDP_BUILD_VENV:-.venv-build}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -r requirements-build.txt
python -m pip install -e . --no-build-isolation
python -m PyInstaller --clean --noconfirm qdp.spec

ARTIFACT=''
if [[ -f dist/qdp/qdp.exe ]]; then
  ARTIFACT='dist/qdp/qdp.exe'
elif [[ -f dist/qdp/qdp ]]; then
  ARTIFACT='dist/qdp/qdp'
elif [[ -f dist/qdp.exe ]]; then
  ARTIFACT='dist/qdp.exe'
elif [[ -f dist/qdp ]]; then
  ARTIFACT='dist/qdp'
else
  echo 'qdp build error: expected dist artifact was not created (looked for dist/qdp/qdp(.exe) and dist/qdp(.exe))' >&2
  exit 1
fi

chmod +x "$ARTIFACT" 2>/dev/null || true
"$ARTIFACT" --help >/tmp/qdp-build-help.txt

echo "qdp build complete: $ARTIFACT"

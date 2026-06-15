#!/usr/bin/env bash
set -euo pipefail

# qdp cross-platform one-click installer
# Supports: macOS, Linux, Windows (Git Bash/WSL/PowerShell), Android (Termux)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/lingion/qdp/main/install.sh | bash
#   bash install.sh [install-dir]

INSTALL_DIR="${1:-}"
REPO_URL="https://github.com/lingion/qdp.git"

# ═══════════════════════════════════════════════════════════════════
#  Platform Detection
# ═══════════════════════════════════════════════════════════════════

detect_platform() {
    local os arch

    # Termux (Android)
    if [ -n "${TERMUX_VERSION:-}" ] || [ -d "/data/data/com.termux" ]; then
        echo "termux"
        return
    fi

    # Cygwin / MSYS2 / Git Bash (Windows)
    if [ -n "${MSYSTEM:-}" ] || [ -n "${CYGWIN:-}" ]; then
        echo "windows-bash"
        return
    fi

    # WSL (Windows Subsystem for Linux)
    if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
        echo "wsl"
        return
    fi

    # OS detection
    os="$(uname -s 2>/dev/null || echo unknown)"
    case "$os" in
        Darwin)        echo "macos"   ;;
        Linux)         echo "linux"   ;;
        MINGW*|MSYS*)  echo "windows-bash" ;;
        CYGWIN*)       echo "windows-bash" ;;
        FreeBSD)       echo "freebsd" ;;
        *)             echo "unknown:$os" ;;
    esac
}

PLATFORM="$(detect_platform)"

# Default install directory per platform
default_install_dir() {
    case "$PLATFORM" in
        termux)        echo "$HOME/qdp"           ;;
        macos)         echo "$HOME/qdp"           ;;
        linux)         echo "$HOME/qdp"           ;;
        wsl)           echo "$HOME/qdp"           ;;
        windows-bash)  echo "$USERPROFILE/qdp" 2>/dev/null || echo "$HOME/qdp" ;;
        freebsd)       echo "$HOME/qdp"           ;;
        *)             echo "$HOME/qdp"           ;;
    esac
}

if [ -z "$INSTALL_DIR" ]; then
    INSTALL_DIR="$(default_install_dir)"
fi

# ═══════════════════════════════════════════════════════════════════
#  Banner
# ═══════════════════════════════════════════════════════════════════

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║       qdp cross-platform installer        ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  Platform : $PLATFORM"
echo "  Install  : $INSTALL_DIR"
echo ""

# ═══════════════════════════════════════════════════════════════════
#  Preflight: ensure git + python available
# ═══════════════════════════════════════════════════════════════════

ensure_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "✗ '$1' not found."
        case "$PLATFORM" in
            termux)
                echo "  Run: pkg install $2"
                ;;
            macos)
                echo "  Install Xcode Command Line Tools: xcode-select --install"
                echo "  Or use Homebrew: brew install $2"
                ;;
            linux|wsl)
                echo "  Debian/Ubuntu: sudo apt install -y $2"
                echo "  Fedora:        sudo dnf install -y $2"
                echo "  Arch:          sudo pacman -S $2"
                ;;
            windows-bash)
                echo "  Install Git for Windows (includes git bash): https://git-scm.com/download/win"
                ;;
            freebsd)
                echo "  Run: sudo pkg install $2"
                ;;
        esac
        return 1
    fi
}

echo "→ Checking prerequisites ..."

if ! ensure_dep git git; then
    exit 1
fi

# Python detection (try multiple names)
PYTHON=""
for candidate in python3 python python3.12 python3.11 python3.10 python3.9; do
    if command -v "$candidate" &>/dev/null; then
        major=$("$candidate" -c 'import sys;print(sys.version_info.major)' 2>/dev/null || echo "0")
        minor=$("$candidate" -c 'import sys;print(sys.version_info.minor)' 2>/dev/null || echo "0")
        if [ "$major" -ge 3 ] 2>/dev/null && [ "$minor" -ge 9 ] 2>/dev/null; then
            PYTHON="$candidate"
            echo "  Python: $candidate ($("$candidate" --version 2>&1))"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "✗ Python 3.9+ not found."
    case "$PLATFORM" in
        termux)
            echo "  Run: pkg install python"
            ;;
        macos)
            echo "  Install from https://python.org or: brew install python"
            ;;
        linux|wsl)
            echo "  Debian/Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
            echo "  Fedora:        sudo dnf install -y python3"
            ;;
        windows-bash)
            echo "  Install from https://python.org (check 'Add to PATH')"
            ;;
        freebsd)
            echo "  Run: sudo pkg install python3"
            ;;
    esac
    exit 1
fi

# Termux: ensure pip + venv module
if [ "$PLATFORM" = "termux" ]; then
    if ! "$PYTHON" -m venv --help &>/dev/null; then
        echo "→ Installing python-venv for Termux ..."
        pkg install -y python-static python-venv 2>/dev/null || pip install virtualenv
    fi
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
#  1. Clone or Update
# ═══════════════════════════════════════════════════════════════════

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "→ Found existing repo, pulling latest ..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main || {
        echo "  Pull failed (maybe local changes). Continuing with existing code."
    }
else
    echo "→ Cloning qdp from GitHub ..."
    git clone "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
#  2. Virtual Environment
# ═══════════════════════════════════════════════════════════════════

# Windows native (no WSL) — use Scripts instead of bin
VENV_ACTIVATE=".venv/bin/activate"
if [ "$PLATFORM" = "windows-bash" ] && [ -d ".venv/Scripts" ]; then
    VENV_ACTIVATE=".venv/Scripts/activate"
fi

if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment ..."
    "$PYTHON" -m venv .venv
fi

# shellcheck disable=SC1090
source "$VENV_ACTIVATE"

echo "→ Upgrading pip ..."
python -m pip install --upgrade pip setuptools wheel --quiet

echo ""

# ═══════════════════════════════════════════════════════════════════
#  3. Install Dependencies
# ═══════════════════════════════════════════════════════════════════

# Termux: install binary deps that some Python packages need
if [ "$PLATFORM" = "termux" ]; then
    echo "→ Installing Termux system dependencies ..."
    pkg install -y ffmpeg libjpeg-turbo zlib 2>/dev/null || true
    # Termux pip: some packages need --no-binary
    export CFLAGS="-Wno-error=implicit-function-declaration"
fi

echo "→ Installing runtime dependencies ..."
python -m pip install -r requirements.txt --quiet

echo "→ Installing qdp (editable mode) ..."
python -m pip install -e . --no-build-isolation --quiet

echo ""

# ═══════════════════════════════════════════════════════════════════
#  4. Verify
# ═══════════════════════════════════════════════════════════════════

echo "→ Verifying installation ..."
if python -m qdp --version &>/dev/null; then
    VERSION=$(python -m qdp --version 2>/dev/null)
    echo "  ✅ qdp $VERSION installed"
else
    echo "  ✅ qdp installed (run 'qdp --help' to verify)"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════
#  5. Platform-specific Notes
# ═══════════════════════════════════════════════════════════════════

echo "─────────────────────────────────────────────"
echo "  Installation complete!"
echo ""

case "$PLATFORM" in
    termux)
        echo "  Termux (Android) notes:"
        echo "    cd $INSTALL_DIR"
        echo "    source .venv/bin/activate"
        echo "    qdp -r                # config wizard"
        echo "    qdp -s 'search term'  # search & download"
        echo ""
        echo "    Web player:"
        echo "    python -m qdp.web.server"
        echo "    → http://127.0.0.1:17890/"
        ;;
    macos)
        echo "  macOS notes:"
        echo "    cd $INSTALL_DIR"
        echo "    source .venv/bin/activate"
        echo "    qdp -r                # config wizard"
        echo "    qdp -s 'search term'"
        echo ""
        echo "    Web player:"
        echo "    python3 -m qdp.web.server"
        ;;
    linux|wsl|freebsd)
        echo "  Linux notes:"
        echo "    cd $INSTALL_DIR"
        echo "    source .venv/bin/activate"
        echo "    qdp -r                # config wizard"
        echo "    qdp -s 'search term'"
        echo ""
        echo "    Web player:"
        echo "    python3 -m qdp.web.server"
        ;;
    windows-bash)
        echo "  Windows (Git Bash) notes:"
        echo "    cd $INSTALL_DIR"
        echo "    source .venv/Scripts/activate"
        echo "    qdp -r                # config wizard"
        echo "    qdp -s 'search term'"
        echo ""
        echo "    Or use PowerShell:"
        echo "    cd $INSTALL_DIR"
        echo "    .venv\\Scripts\\Activate.ps1"
        echo "    qdp -r"
        ;;
esac

echo ""
echo "  One-liner update (any platform):"
echo "    bash install.sh"
echo "─────────────────────────────────────────────"
echo ""

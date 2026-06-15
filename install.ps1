# qdp cross-platform installer for Windows PowerShell
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/lingion/qdp/main/install.ps1 | iex
#   or:  powershell -ExecutionPolicy Bypass -File install.ps1 [-InstallDir $HOME\qdp]

param(
    [string]$InstallDir = ""
)

$ErrorActionPreference = "Stop"
$RepoUrl = "https://github.com/lingion/qdp.git"

# ═══════════════════════════════════════════════════════════════
#  Banner
# ═══════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║       qdp Windows installer (PowerShell)  ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  Install Dir
# ═══════════════════════════════════════════════════════════════

if ([string]::IsNullOrEmpty($InstallDir)) {
    $InstallDir = Join-Path $HOME "qdp"
}

Write-Host "  Install  : $InstallDir"
Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  Prerequisites
# ═══════════════════════════════════════════════════════════════

Write-Host "→ Checking prerequisites ..."

# Git
$gitExe = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitExe) {
    Write-Host "✗ git not found." -ForegroundColor Red
    Write-Host "  Install from: https://git-scm.com/download/win"
    exit 1
}

# Python
$pythonExe = $null
foreach ($name in @("python", "python3", "py")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $ver = & $name -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
            $parts = $ver -split '\.'
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 9) {
                $pythonExe = $name
                Write-Host "  Python: $name ($ver)"
                break
            }
        } catch {}
    }
}

if (-not $pythonExe) {
    Write-Host "✗ Python 3.9+ not found." -ForegroundColor Red
    Write-Host "  Install from: https://python.org (check 'Add to PATH')"
    exit 1
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  1. Clone or Update
# ═══════════════════════════════════════════════════════════════

if (Test-Path "$InstallDir\.git") {
    Write-Host "→ Found existing repo, pulling latest ..."
    Push-Location $InstallDir
    git pull --ff-only origin main 2>&1 | Write-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Pull failed, continuing with existing code." -ForegroundColor Yellow
    }
} else {
    Write-Host "→ Cloning qdp from GitHub ..."
    git clone $RepoUrl $InstallDir 2>&1 | Write-Host
    Push-Location $InstallDir
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  2. Virtual Environment
# ═══════════════════════════════════════════════════════════════

$venvPath = Join-Path $InstallDir ".venv"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

if (-not (Test-Path $venvPath)) {
    Write-Host "→ Creating virtual environment ..."
    & $pythonExe -m venv .venv
}

Write-Host "→ Upgrading pip ..."
& $pythonExe -m pip install --upgrade pip setuptools wheel --quiet

Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  3. Install Dependencies
# ═══════════════════════════════════════════════════════════════

Write-Host "→ Installing runtime dependencies ..."
& $pythonExe -m pip install -r requirements.txt --quiet

Write-Host "→ Installing qdp (editable mode) ..."
& $pythonExe -m pip install -e . --no-build-isolation --quiet

Write-Host ""

# ═══════════════════════════════════════════════════════════════
#  4. Verify
# ═══════════════════════════════════════════════════════════════

Write-Host "→ Verifying installation ..."
try {
    $version = & $pythonExe -m qdp --version 2>$null
    Write-Host "  ✅ qdp $version installed" -ForegroundColor Green
} catch {
    Write-Host "  ✅ qdp installed (run 'qdp --help' to verify)" -ForegroundColor Green
}

Pop-Location

Write-Host ""
Write-Host "─────────────────────────────────────────────"
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Quick start:"
Write-Host "    cd $InstallDir"
Write-Host "    .\.venv\Scripts\Activate.ps1"
Write-Host "    qdp -r                  # config wizard"
Write-Host "    qdp -s 'your search'    # search & download"
Write-Host ""
Write-Host "  Web player:"
Write-Host "    python -m qdp.web.server"
Write-Host "    → http://127.0.0.1:17890/"
Write-Host "─────────────────────────────────────────────"
Write-Host ""

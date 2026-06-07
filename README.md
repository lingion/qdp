# QDP

A local Qobuz toolkit — CLI downloader + web player, ready to use.

## Features

- **CLI/TUI interactive downloader** — search and download albums, tracks, playlists; Hi-Res FLAC supported
- **Local web player** — open in browser, full playback queue, playlist management, quality switching
- **Multi-account management** — email/password or token login, switch freely
- **Proxy pool** — configure multiple proxy nodes with automatic rotation and fallback to direct
- **Integrity verification** — auto-verify downloads, repair and re-download missing tracks

## Quick Start

### Requirements

- Python 3.9+
- pip
- A Qobuz account (paid subscription)

### Install

```bash
git clone https://github.com/lingion/qdp.git
cd qdp

python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e . --no-build-isolation
```

### First-time Setup

```bash
qdp -r
```

The config wizard will walk you through:
1. **Login method** — email/password (recommended) or token
2. **Key selection** — default Android key (works out of box), auto-fetch web key, or manually enter your own App ID / Secret
3. **Download directory** — defaults to `Qobuz Downloads` in current directory
4. **Quality preference** — MP3, 16-bit FLAC, 24-bit Hi-Res, etc.

### Usage

```bash
# Launch interactive UI (recommended)
qdp

# Command-line search
qdp -s "Beatles"
qdp -sa "Abbey Road"    # search albums
qdp -st "Yesterday"     # search tracks

# Download from URL
qdp "https://www.qobuz.com/album/xxxxx"

# Help & version
qdp --help
qdp --version
```

## Web Player

```bash
# Option 1: from TUI, type w + Enter
qdp

# Option 2: start server directly
python3 -m qdp.web.server
```

Opens browser automatically, typically at `http://127.0.0.1:17890/`

### Features

- Search and play from Qobuz catalog
- Queue management (drag reorder, repeat, shuffle)
- Real-time quality switching (keeps playback position)
- Track/album download
- Playlist management
- Multi-account switching
- Discover page (random recommendations)
- File browser (browse downloaded music)

### Environment Variables

| Variable | Description |
|----------|-------------|
| `QDP_WEB_HOST` | Bind address (default `127.0.0.1`) |
| `QDP_WEB_PORT` | Bind port (default `17890`) |
| `QDP_BUNDLE_URL` | Custom Qobuz mirror URL (for web key fetching) |
| `QDP_APP_ID` | Qobuz App ID |
| `QDP_AUTH_TOKEN` | Qobuz auth token |

## Proxy Configuration

Add a `proxies` field in config (via wizard or edit `~/.config/qobuz-dl/config.ini`):

```ini
[DEFAULT]
proxies = https://proxy1.example.com,https://proxy2.example.com
```

Downloads and API requests automatically rotate through proxies. Falls back to direct connection if all proxies fail.

## Dependencies

Core (`requirements.txt`):
- `pathvalidate` — safe filename handling
- `requests` — HTTP requests
- `mutagen` — audio metadata read/write
- `beautifulsoup4` — HTML parsing
- `rich` — terminal rich output

Build (`requirements-build.txt`): includes PyInstaller etc., needed for packaging.

## Testing

```bash
python -m pip install -r requirements-build.txt
python -m pytest -q
```

## Packaging

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm qdp.spec
```

Output in `dist/qdp/`.

## Project Structure

```
qdp/
├── cli.py           # CLI entry point
├── ui.py            # TUI interactive interface
├── core.py          # Core download logic
├── downloader.py    # Download pipeline (retry, proxy, concurrency)
├── qopy.py          # Qobuz API client
├── config.py        # Config wizard
├── accounts.py      # Multi-account management
├── integrity.py     # Integrity verification
├── metadata.py      # Audio tag writing
├── db.py            # Download record database
├── bundle.py        # Web key fetching
├── sidecar.py       # Sidecar metadata
├── web/
│   ├── server.py    # Local web server
│   └── app/         # Frontend (HTML/JS/CSS)
├── tests/           # Automated tests
└── docs/            # Project docs
```

## Maintainers

- **Lingion** — mainline integration, infrastructure, deployment, code quality
- **Kerry1020** — web player, frontend UI, browser interaction

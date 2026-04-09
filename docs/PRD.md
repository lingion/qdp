# QDP Recovered Product Specification

## Status
This document reconstructs the missing or implicit product contract from the current repository so Sprint 1 has a clear source of truth.

## Product Summary
QDP is a local-first Qobuz toolkit with two visible product surfaces already present in the codebase:
- a mature CLI/TUI downloader and library-management workflow
- a local web player runtime in `qdp/web/server.py` that serves a browser UI, proxies authenticated Qobuz API traffic, and relays playback streams

Sprint 1 does **not** redefine the product. It captures what the repository already implies, sets scope boundaries, and establishes safe delivery conventions for future sprints.

## Goals
- Recover a usable product contract from the existing repository.
- Define what counts as the deliverable for the current web-player-oriented sprint track.
- Document install, run, test, and packaging expectations.
- Establish backup and restore discipline before further implementation.
- Track key files that later sprints must revisit.

## Problem Statement
The repository contains substantial implementation, but the product boundary for the current sprint track was not documented in-repo. That creates risk around scope creep, unsafe file changes, and ambiguity about which files are foundational versus later-sprint targets.

## Users
- Operators running QDP locally from source.
- Developers extending the web player and packaging flow.
- Evaluators verifying that the repository can be installed, run, tested, and packaged from documented instructions.

## In Scope
### Current product capabilities inferred from the repository
- CLI/TUI entrypoint via `qdp.cli` and `qdp.__main__`
- Account switching and account metadata support via `qdp/accounts.py`
- Local web player backend in `qdp/web/server.py`
- Browser app assets in `qdp/web/app/`
- Qobuz API proxying and stream relaying
- Source installation and local execution
- Packaging support through `setup.py`, `qdp.spec`, and build scripts
- Test execution from the `tests/` directory

### Sprint 1 scope
- Write the recovered PRD
- Document backup and restore rules
- Provide visible dependency/runtime metadata
- Add or update environment examples
- Define repository-level done criteria
- Record a repository scan of critical implementation and packaging files

## Out of Scope
- Redesigning downloader, account, or web-player features in Sprint 1
- Major backend refactors
- New product areas unrelated to Qobuz download/playback workflows
- Cloud deployment, hosted APIs, or mobile clients
- Replacing the existing CLI/TUI architecture

## Functional Expectations
### Core application
- Users can install QDP from source and run CLI/TUI flows.
- Users can launch the local web player runtime.
- The web player serves local app assets and rewrites browser requests through a local proxy.
- Authenticated Qobuz requests are sent using configured credentials.
- Stream URLs are relayed through `/stream` so playback stays inside the local runtime.

### Operational baseline
- Packaging commands are documented and runnable.
- Test commands are documented and point to the existing `tests/` suite.
- Modified files are backed up before changes proceed.

## Release Assumptions
- Python 3.11+ is the intended practical runtime baseline for current local development.
- Source installation via pip is the primary supported path.
- `requests` and other runtime dependencies come from `requirements.txt` / package metadata.
- Packaging currently targets PyInstaller-based executable output via `qdp.spec` and build helper scripts.
- Secrets and account tokens live in user configuration, not in committed repository files.
- The web player depends on a local config/account context rather than a hosted auth service.

## Repository Scan: Key Files and Current Status
### Core runtime
- `qdp/__main__.py` — CLI module entrypoint
- `qdp/cli.py` — primary command surface
- `qdp/ui.py` — interactive UI/TUI logic
- `qdp/accounts.py` — account persistence and switching logic
- `qdp/web/server.py` — local web player server and proxy runtime

### Web app files targeted by later sprint verification
- `qdp/web/app/index.html` — browser shell
- `qdp/web/app/app.js` — web-player client behavior
- `qdp/web/app/app.css` — web-player styling
- `qdp/web/README.md` — web module documentation

### Packaging and build files targeted by later sprint verification
- `qdp.spec` — PyInstaller spec
- `build_windows.bat` — Windows build helper
- `build_windows.ps1` — PowerShell build helper
- `build_windows.sh` — containerized/non-Windows build helper
- `setup.py` — package metadata and console entrypoint
- `requirements-build.txt` — build-time dependency list

### Verification files
- `tests/` — existing automated test suite
- `README.md` — operator-facing usage and packaging documentation

## Known Risks
- The repo mixes downloader/TUI and web-player concerns, so future sprint work must avoid accidental scope drift.
- Web player behavior depends on valid local account/config data.
- Packaging may lag behind runtime changes unless `qdp.spec`, helper scripts, and docs are kept in sync.

## Definition of Done
See `docs/definition-of-done.md`.

## Backup and Restore
See `docs/backup-and-restore.md`.

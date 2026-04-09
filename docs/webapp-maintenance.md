# Webapp Maintenance Notes

## Scope
This document tracks the webapp-oriented maintenance surface of QDP.

### Kerry1020 primary responsibility
- web UI structure and readability
- interaction-facing module organization
- search / player / queue UI discoverability
- browser-side testing and behavior validation

## Current webapp entry points
- `qdp/web/server.py`
- `qdp/web/app/index.html`
- `qdp/web/app/app.js`
- `qdp/web/app/discover.js`
- `qdp/web/app/player.js`
- `qdp/web/app/playlists.js`
- `qdp/web/app/queue.js`
- `qdp/web/app/accounts.js`

## Maintenance suggestions
1. Keep app-layer files small and task-focused.
2. Separate browser UI concerns from backend/runtime concerns.
3. Prefer adding contract checks when changing player/discover/search behavior.
4. Treat webapp docs as a first-class part of delivery, not an afterthought.

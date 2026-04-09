from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_web_player_frontend_contract():
    root = REPO_ROOT
    index_html = (root / 'qdp/web/app/index.html').read_text(encoding='utf-8')
    app_js = (root / 'qdp/web/app/app.js').read_text(encoding='utf-8')
    core_js = (root / 'qdp/web/app/core.js').read_text(encoding='utf-8')
    player_js = (root / 'qdp/web/app/player.js').read_text(encoding='utf-8')
    queue_js = (root / 'qdp/web/app/queue.js').read_text(encoding='utf-8')
    playlists_js = (root / 'qdp/web/app/playlists.js').read_text(encoding='utf-8')
    api_js = (root / 'qdp/web/app/api.js').read_text(encoding='utf-8')
    accounts_js = (root / 'qdp/web/app/accounts.js').read_text(encoding='utf-8')
    discover_js = (root / 'qdp/web/app/discover.js').read_text(encoding='utf-8')
    script_paths = [
        '/app/core.js',
        '/app/accounts.js',
        '/app/queue.js',
        '/app/playlists.js',
        '/app/api.js',
        '/app/discover.js',
        '/app/player.js',
        '/app/app.js',
    ]
    app_css = (root / 'qdp/web/app/app.css').read_text(encoding='utf-8')
    server_py = (root / 'qdp/web/server.py').read_text(encoding='utf-8')

    # visible versioning
    assert 'appVersion' in index_html
    assert 'APP_VERSION' in core_js
    assert 'loadMeta' in app_js
    assert '/api/meta' in app_js
    for script_path in script_paths:
        assert script_path in index_html
    assert '__version__' in (root / 'qdp/web/__init__.py').read_text(encoding='utf-8')
    assert 'WEB_PLAYER_VERSION' in server_py

    # core player controls
    assert 'id="prev"' in index_html
    assert 'id="play"' in index_html
    assert 'id="next"' in index_html
    assert 'id="qualitySelect"' in index_html
    assert 'id="seek"' in index_html

    # queue / playlists sidebar
    assert 'id="queue"' in index_html
    assert 'id="myPlaylists"' in index_html
    assert 'mobileSidebarToggle' in index_html

    # download quality menu
    assert 'id="downloadMenu"' in index_html
    assert 'DOWNLOAD_FORMAT_OPTIONS' in core_js
    assert 'openDownloadMenu' in core_js
    assert 'triggerTrackDownload' in core_js
    assert '/api/download?id=${id}&fmt=${fmt}' in core_js

    # quality switch for current track
    assert 'swapCurrentTrackQuality' in player_js
    assert "qualitySelect').addEventListener('change'" in app_js
    assert 'audio.currentTime = Math.max(0, nextTime)' in player_js or 'audio.currentTime = nextTime' in player_js

    # keyboard shortcut
    assert "document.addEventListener('keydown'" in app_js
    assert 'shouldIgnoreSpaceToggle' in app_js

    # queue drag support
    assert 'queueDrag' in core_js
    assert 'reorderQueueItems' in queue_js
    assert 'commitQueueReorder' in queue_js
    assert 'syncPlaylistContextAfterQueueReorder' in queue_js
    assert 'canReorderCurrentQueue' in queue_js
    assert 'renderQueue();\n        syncAuxiliaryUi();\n        await playCurrent(\'queue-click\')' in queue_js

    # module responsibilities remain discoverable
    assert 'loadAccounts' in accounts_js
    assert 'search' in api_js
    assert 'loadDiscoverRandom' in discover_js
    assert 'renderPlaylists' in playlists_js

    # mobile drawer polish
    assert 'mobileSidebarOverlay' in index_html
    assert '.mobileSidebarOverlay' in app_css
    assert 'onMobileDrawerTouchStart' in app_js

    # action sheet / menu polish styling exists
    assert '.downloadMenuCard' in app_css
    assert '.downloadMenuOption' in app_css

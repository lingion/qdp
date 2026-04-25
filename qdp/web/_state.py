"""Shared state, caches, Client lifecycle, and HTML monkey-patching for the QDP web server.

This module owns all module-level mutable state used across the web layer:
request trace ring buffer, web server singletons, client/entity caches, and
the big HTML monkey-patching function that rewrites upstream Qobuz pages for
local playback.

It also provides helpers for building and caching ``qdp.qopy.Client`` instances
so that configuration changes (account switches, credential updates) are
reflected without restarting the server.
"""

from __future__ import annotations

import collections
import contextlib
import io
import logging
import os
import re
import threading
import time
from typing import Dict, Optional, Tuple

from qdp.qopy import Client
from qdp.accounts import get_active_account
from qdp.config import CONFIG_FILE
from qdp.web._helpers import (
    _CONFIG_CACHE,
    _get_runtime_defaults,
    _safe_join,
    _DEFAULT_USER_AGENT,
    _ASSET_CACHE_ROOT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_TRACE_LIMIT = 200
_REQUEST_TRACE = collections.deque(maxlen=_TRACE_LIMIT)

_WEB_SERVER = None
_WEB_THREAD = None
_WEB_URL = None

_CLIENT_CACHE_LOCK = threading.Lock()
_CLIENT_CACHE: Dict[str, Client] = {}

_ENTITY_CACHE_LOCK = threading.Lock()
_ENTITY_CACHE: Dict[tuple, dict] = {}
_ENTITY_CACHE_TTL = 1800
_ENTITY_CACHE_MAX_SIZE = 500

_DISCOVER_RANDOM_SEEDS = ["jazz", "classical", "pop", "new", "electronic", "soundtrack"]

# ---------------------------------------------------------------------------
# HTML monkey-patching
# ---------------------------------------------------------------------------


def _inject_monkey_patch(html: str) -> str:
    """Inject fetch/XHR rewrite + getFileUrl stream rewrite."""

    script = r"""
<script>
(function(){
  const API_PREFIXES = [
    'https://www.qobuz.com/api.json/0.2/',
    'https://www.qobuz.com/api.json/0.2',
    'https://play.qobuz.com/api.json/0.2/',
    'https://play.qobuz.com/api.json/0.2',
    '//www.qobuz.com/api.json/0.2/',
    '//www.qobuz.com/api.json/0.2',
    '//play.qobuz.com/api.json/0.2/',
    '//play.qobuz.com/api.json/0.2',
    '/api.json/0.2/',
    'api.json/0.2/'
  ];

  function rewriteUrl(u){
    try {
      if(!u) return u;
      const s = String(u);
      for (const p of API_PREFIXES){
        if (s.startsWith(p)){
          const rest = s.substring(p.length);
          return '/api.json/0.2/' + rest;
        }
      }
      return s;
    } catch(e){ return u; }
  }

  // route guard: never stay on /login for local player
  function forceDiscover(){
    try {
      if (location && location.pathname === '/login') {
        history.replaceState(null, '', '/discover');
      }
    } catch(e) {}
  }

  const _pushState = history.pushState;
  history.pushState = function(state, title, url){
    try {
      if (typeof url === 'string' && url.startsWith('/login')) url = '/discover';
      const args = Array.prototype.slice.call(arguments);
      args[2] = url;
      const ret = _pushState.apply(this, args);
      forceDiscover();
      return ret;
    } catch(e) {
      return _pushState.apply(this, arguments);
    }
  };

  const _replaceState = history.replaceState;
  history.replaceState = function(state, title, url){
    try {
      if (typeof url === 'string' && url.startsWith('/login')) url = '/discover';
      const args = Array.prototype.slice.call(arguments);
      args[2] = url;
      const ret = _replaceState.apply(this, args);
      forceDiscover();
      return ret;
    } catch(e) {
      return _replaceState.apply(this, arguments);
    }
  };

  // Some routers set pathname after async checks: keep policing for a while
  forceDiscover();
  let __qdp_guard_ticks = 0;
  const __qdp_guard = setInterval(function(){
    __qdp_guard_ticks++;
    forceDiscover();
    if (__qdp_guard_ticks > 200) clearInterval(__qdp_guard); // ~20s
  }, 100);
  window.addEventListener('popstate', forceDiscover);

  // disable analytics/trackers that can break offline/local mode
  try {
    const blocked = ['googletagmanager', 'gtm.js', 'mixpanel', 'clarity', 'braze', 'pixel', 'privacy-center', 'didomi', 'algolia', 'search-insights'];
    const nodes = Array.from(document.querySelectorAll('script[src]'));
    for (const n of nodes) {
      const src = String(n.getAttribute('src')||'');
      if (blocked.some(k => src.includes(k))) {
        n.parentNode && n.parentNode.removeChild(n);
      }
    }
  } catch(e) {}

  // patch fetch
  const _fetch = window.fetch;
  window.fetch = function(input, init){
    try {
      if (typeof input === 'string') {
        input = rewriteUrl(input);
      } else if (input && input.url) {
        const nu = rewriteUrl(input.url);
        if (nu !== input.url) {
          input = new Request(nu, input);
        }
      }
    } catch(e) {}

    return _fetch.call(this, input, init).then(async (resp) => {
      try {
        const url = (resp && resp.url) ? String(resp.url) : '';
        if (url.includes('/api.json/0.2/track/getFileUrl')) {
          const clone = resp.clone();
          const data = await clone.json();
          if (data && data.url && typeof data.url === 'string') {
            const proxied = '/stream?url=' + encodeURIComponent(data.url);
            data.url = proxied;
            return new Response(JSON.stringify(data), {
              status: resp.status,
              statusText: resp.statusText,
              headers: resp.headers
            });
          }
        }
      } catch(e) {}
      return resp;
    });
  };

  // patch XHR open
  const _open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url){
    try { url = rewriteUrl(url); } catch(e) {}
    return _open.apply(this, arguments);
  };
})();
</script>
"""

    # inject ASAP: right after <head> so it runs before any external async scripts
    lower = html.lower()
    head_idx = lower.find("<head")
    if head_idx != -1:
        gt = lower.find(">", head_idx)
        if gt != -1:
            return html[: gt + 1] + script + html[gt + 1 :]

    # fallback: before </head> or </body>
    idx = lower.rfind("</head>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    idx = lower.rfind("</body>")
    if idx != -1:
        return html[:idx] + script + html[idx:]
    return html + script


# ---------------------------------------------------------------------------
# Upstream / asset helpers
# ---------------------------------------------------------------------------


def _upstream_play_base() -> str:
    # assets should always come from play.qobuz.com
    return "https://play.qobuz.com"


def _asset_cache_path(path: str) -> str:
    # path like /assets/.. or /legacy/..
    rel = path.lstrip("/")
    return _safe_join(_ASSET_CACHE_ROOT, rel)


# ---------------------------------------------------------------------------
# Client cache
# ---------------------------------------------------------------------------


def _client_cache_key(defaults: Optional[dict] = None) -> str:
    defaults = defaults or _get_runtime_defaults()
    active_account = get_active_account(CONFIG_FILE) or "default"
    cache_parts = [
        active_account,
        defaults.get("use_token", ""),
        defaults.get("email", ""),
        defaults.get("password", ""),
        defaults.get("user_id", ""),
        defaults.get("app_id", ""),
        defaults.get("user_auth_token", ""),
        defaults.get("secrets", ""),
    ]
    return "|".join(str(part) for part in cache_parts)


def _clear_client_cache() -> None:
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()
    with _ENTITY_CACHE_LOCK:
        _ENTITY_CACHE.clear()
    _CONFIG_CACHE["data"] = None


# ---------------------------------------------------------------------------
# Entity cache
# ---------------------------------------------------------------------------


def _cache_get(bucket: str, entity_id: str):
    now = time.time()
    key = (bucket, str(entity_id))
    with _ENTITY_CACHE_LOCK:
        item = _ENTITY_CACHE.get(key)
        if not item:
            return None
        if now - float(item.get("ts", 0)) > _ENTITY_CACHE_TTL:
            _ENTITY_CACHE.pop(key, None)
            return None
        return item.get("value")


def _cache_set(bucket: str, entity_id: str, value: dict):
    key = (bucket, str(entity_id))
    with _ENTITY_CACHE_LOCK:
        _ENTITY_CACHE[key] = {"ts": time.time(), "value": value}
        _cache_cleanup()
    return value


def _cache_cleanup():
    """Remove expired and excess entries from entity cache."""
    now = time.time()
    # Remove expired
    expired = [k for k, v in _ENTITY_CACHE.items()
               if now - v.get("ts", 0) > _ENTITY_CACHE_TTL]
    for k in expired:
        del _ENTITY_CACHE[k]
    # If still over limit, remove oldest
    if len(_ENTITY_CACHE) > _ENTITY_CACHE_MAX_SIZE:
        sorted_keys = sorted(_ENTITY_CACHE.items(), key=lambda x: x[1].get("ts", 0))
        for k, _ in sorted_keys[:len(_ENTITY_CACHE) - _ENTITY_CACHE_MAX_SIZE]:
            del _ENTITY_CACHE[k]


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


def _get_client() -> Client:
    defaults = _get_runtime_defaults()
    key = _client_cache_key(defaults)
    with _CLIENT_CACHE_LOCK:
        client = _CLIENT_CACHE.get(key)
        if client is not None:
            return client
    client = _build_client_from_config()
    setattr(client, "active_account", get_active_account(CONFIG_FILE) or "")
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()
        _CLIENT_CACHE[key] = client
    return client


def _build_client_from_config() -> Client:
    defaults = _get_runtime_defaults()
    secrets = [s for s in (defaults.get("secrets") or "").split(",") if s]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return Client(
            defaults.get("email", ""),
            defaults.get("password", ""),
            defaults.get("app_id", ""),
            secrets,
            defaults.get("use_token", "false"),
            defaults.get("user_id", ""),
            defaults.get("user_auth_token", ""),
        )

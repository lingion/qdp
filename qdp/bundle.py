import base64
import logging
import re
from collections import OrderedDict
from urllib.parse import quote

from requests import Session

# Modified code based on DashLt's spoofbuz

logger = logging.getLogger(__name__)

_SEED_TIMEZONE_REGEX = re.compile(
    r'[a-z]\.initialSeed\("(?P<seed>[\w=]+)",window\.utimezone\.(?P<timezone>[a-z]+)\)'
)
_INFO_EXTRAS_REGEX = r'name:"\w+/(?P<timezone>{timezones})",info:"(?P<info>[\w=]+)",extras:"(?P<extras>[\w=]+)"'
_APP_ID_REGEX = re.compile(
    r'production:{api:{appId:"(?P<app_id>\d{9})",appSecret:"\w{32}"'
)

_BUNDLE_URL_REGEX = re.compile(
    r'<script src="(/resources/\d+\.\d+\.\d+-[a-z]\d{3}/bundle\.js)"></script>'
)

# Base URLs to try in order; earlier entries take priority.
# Users can override via QDP_BUNDLE_URL env var.
_BASE_URLS = [
    "https://play.qobuz.com",
]

def _get_base_urls():
    """Return the ordered list of base URLs, allowing env override."""
    import os
    env = os.environ.get("QDP_BUNDLE_URL", "").strip()
    if env:
        return [env]
    return _BASE_URLS


def _proxy_fetch(session, path, timeout):
    """Fetch a play.qobuz.com path through the configured reverse proxy.

    play.qobuz.com is unreachable from CN networks; the qdp reverse proxy
    (same one API calls use) exposes a /proxy?url= passthrough. Returns the
    response or None when no proxy is configured / the fetch fails.
    """
    try:
        from qdp.utils import get_active_proxy

        proxy_host = get_active_proxy()
    except Exception as exc:  # pragma: no cover - config layer failure
        logger.debug("Proxy lookup failed: %s", exc)
        return None
    if not proxy_host:
        return None
    try:
        return session.get(
            proxy_host.rstrip("/") + "/proxy?url=" + quote("https://play.qobuz.com" + path, safe=""),
            timeout=timeout,
        )
    except Exception as exc:
        logger.debug("Proxy fetch failed for %s: %s", path, exc)
        return None


class Bundle:
    def __init__(self):
        self._session = Session()

        base_urls = _get_base_urls()
        last_exc = None
        for url in base_urls:
            try:
                logger.debug("Getting login page from %s", url)
                response = self._session.get(f"{url}/login", timeout=15)
                response.raise_for_status()

                bundle_url_match = _BUNDLE_URL_REGEX.search(response.text)
                if not bundle_url_match:
                    logger.debug("Bundle URL pattern not found at %s", url)
                    continue

                bundle_url = bundle_url_match.group(1)

                logger.debug("Getting bundle from %s", url)
                response = self._session.get(url + bundle_url, timeout=30)
                response.raise_for_status()

                self._bundle = response.text
                return
            except Exception as exc:
                logger.debug("Failed to fetch bundle from %s: %s", url, exc)
                last_exc = exc
                continue

        # Direct access failed (CN networks): try the reverse-proxy
        # passthrough for the login page + bundle before giving up.
        login_resp = _proxy_fetch(self._session, "/login", timeout=15)
        bundle_match = _BUNDLE_URL_REGEX.search(login_resp.text) if login_resp is not None and login_resp.status_code == 200 else None
        if bundle_match:
            bundle_resp = _proxy_fetch(self._session, bundle_match.group(1), timeout=60)
            if bundle_resp is not None and bundle_resp.status_code == 200:
                self._bundle = bundle_resp.text
                logger.debug("Bundle fetched via reverse proxy")
                return

        raise NotImplementedError(
            f"Failed to fetch bundle from all known URLs. "
            f"Set QDP_BUNDLE_URL to a working Qobuz mirror. Last error: {last_exc}"
        )

    def get_app_id(self):
        match = _APP_ID_REGEX.search(self._bundle)
        if not match:
            raise NotImplementedError("Failed to match APP ID")

        return match.group("app_id")

    def get_secrets(self):
        logger.debug("Getting secrets")
        seed_matches = _SEED_TIMEZONE_REGEX.finditer(self._bundle)
        secrets = OrderedDict()

        for match in seed_matches:
            seed, timezone = match.group("seed", "timezone")
            secrets[timezone] = [seed]

        keypairs = list(secrets.items())
        secrets.move_to_end(keypairs[1][0], last=False)
        info_extras_regex = _INFO_EXTRAS_REGEX.format(
            timezones="|".join([timezone.capitalize() for timezone in secrets])
        )
        info_extras_matches = re.finditer(info_extras_regex, self._bundle)
        for match in info_extras_matches:
            timezone, info, extras = match.group("timezone", "info", "extras")
            secrets[timezone.lower()] += [info, extras]
        for secret_pair in secrets:
            secrets[secret_pair] = base64.standard_b64decode(
                "".join(secrets[secret_pair])[:-44]
            ).decode("utf-8")
        return secrets

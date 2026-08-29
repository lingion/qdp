import configparser
import hashlib
import logging
import os
import random
import time
from datetime import date

import requests

from qdp.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
    InvalidAppSecretError,
    InvalidQuality,
)
from qdp.utils import get_api_base_url, get_proxy_list, fetch_web_player_credentials
from rich.console import Console

console = Console()
RESET = "请运行 'qdp -r' 重置凭证"

logger = logging.getLogger(__name__)

# 莫兰迪配色
C_TEXT = "#abb2bf"
C_OK   = "#98c379"
C_WARN = "#e5c07b"
C_ERR  = "#e06c75"

# persist_credentials 只允许写这些 key —— 账号身份字段(email/password/token)严禁触碰
_PERSISTABLE_KEYS = ("app_id", "secrets")


def _default_config_file():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or ""
    else:
        base = os.path.join(os.environ.get("XDG_CONFIG_HOME")
                            or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(base, "qobuz-dl", "config.ini")

class Client:
    def __init__(self, email, pwd, app_id, secrets, use_token, user_id, user_auth_token):
        console.print(f"[{C_TEXT}]正在登录 API...[/{C_TEXT}]")
        self.secrets = secrets
        self.id = str(app_id)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
                "X-App-Id": self.id,
                "Content-Type": "application/json;charset=UTF-8"
            }
        )
        
        # 初始化代理列表
        self.proxy_list = get_proxy_list()
        self.base = get_api_base_url()
        
        self.sec = None
        self._auto_fetched_credentials = False
        
        # 对齐 QBDLX：login 前先尝试从 web player 获取最新凭据
        self._pre_fetch_credentials(config_file=_default_config_file())
        
        self.auth(email, pwd, use_token, user_id, user_auth_token)
        self.cfg_setup()
    
    def _pre_fetch_credentials(self, config_file=None):
        """QBDLX 对齐：优先从 web player bundle.js 自动获取 app_id/secret。
        在 login 之前执行，确保 token login 使用正确的 app_id。
        自动爬取成功时落盘,下次启动不再重复爬取。"""
        # 先验证 config secret 是否有效
        for secret in self.secrets:
            if secret and self.test_secret(secret):
                self.sec = secret
                return  # config 凭据有效

        # config secret 失效，从 web player 自动获取
        console.print(f"[{C_WARN}]配置中的 App Secret 已失效，从 web player 自动获取...[/{C_WARN}]")
        auto_id, auto_secrets = fetch_web_player_credentials()
        if auto_id and auto_secrets:
            # 先切到 auto app_id 再测 secret —— secret 签名依赖 X-App-Id header,
            # 旧 app_id + 新 secret 会被 API 以 400 拒绝,导致"全部验证失败"。
            original_id = self.id
            if self.id != str(auto_id):
                self.id = str(auto_id)
                self.session.headers.update({"X-App-Id": self.id})
            # 尝试每个解码出的 secret，找到 getFileUrl 签名通过的那个
            for secret in auto_secrets:
                if self.test_secret(secret):
                    self.sec = secret
                    if original_id != self.id:
                        console.print(f"[{C_OK}]自动更新 app_id: {original_id} → {auto_id}[/{C_OK}]")
                    self._auto_fetched_credentials = True
                    console.print(f"[{C_OK}]Web Player 凭据验证通过！[/{C_OK}]")
                    # 落盘:下次启动直接命中 config 凭据,不再爬取
                    self.persist_credentials(
                        new_app_id=self.id,
                        new_secrets=[self.sec],
                        config_file=config_file,
                    )
                    return
            # 全部失败:还原原 app_id,按原配置兜底
            if original_id != self.id:
                self.id = original_id
                self.session.headers.update({"X-App-Id": self.id})
            console.print(f"[{C_ERR}]获取到 {len(auto_secrets)} 个 secret 但均验证失败。[/{C_ERR}]")
        else:
            console.print(f"[{C_ERR}]自动获取失败。[/{C_ERR}]")
        console.print(f"[{C_ERR}]将使用配置中的值尝试。[/{C_ERR}]")

    def persist_credentials(self, new_app_id, new_secrets, config_file=None):
        """把自动获取的凭据写回 config.ini(DEFAULT + active account section)。

        只写 app_id/secrets 两个 key,严禁触碰账号身份字段(email/password/token)。
        写失败仅告警,不影响本次运行。
        """
        config_file = config_file or _default_config_file()
        merged = ",".join(s for s in (new_secrets or []) if s)
        if not str(new_app_id or "").strip() or not merged:
            return False
        try:
            config = configparser.ConfigParser()
            config.read(config_file)
            payload = {"app_id": str(new_app_id).strip(), "secrets": merged}
            active = ""
            if config.has_section("DEFAULT") or "DEFAULT" in config:
                active = config["DEFAULT"].get("active_account", "").strip()
                config["DEFAULT"].update(payload)
            else:
                config["DEFAULT"].update(payload)
            # 同步 active account section,切号/读 account 时不会回退到旧 secret
            if active:
                section = f"account:{active}"
                if config.has_section(section):
                    for key in _PERSISTABLE_KEYS:
                        config[section][key] = payload[key]
            os.makedirs(os.path.dirname(config_file) or ".", exist_ok=True)
            with open(config_file, "w", encoding="utf-8") as fp:
                config.write(fp)
            console.print(f"[{C_OK}]已将新凭据保存到 {config_file}[/{C_OK}]")
            return True
        except (configparser.Error, OSError) as exc:
            logger.warning("保存自动获取的凭据失败(不影响本次运行): %s", exc)
            return False

    def api_call(self, epoint, **kwargs):
        if epoint == "catalog/search":
            params = {
                "query": kwargs["query"],
                "limit": kwargs["limit"],
                "type": kwargs["type"],
                "offset": kwargs.get("offset", 0),
            }
        elif epoint == "user/login":
            if kwargs["use_token"] == "true":
                params = {"user_id": kwargs["user_id"], "user_auth_token": kwargs["user_auth_token"]}
            else:
                params = {"email": kwargs["email"], "password": kwargs["pwd"], "app_id": self.id}
        elif epoint == "track/get":
            params = {"track_id": kwargs["id"]}
        elif epoint == "album/get":
            params = {"album_id": kwargs["id"]}
        elif epoint == "playlist/get":
            params = {"extra": "tracks", "playlist_id": kwargs["id"], "limit": 500, "offset": kwargs["offset"]}
        elif epoint == "artist/get":
            params = {"app_id": self.id, "artist_id": kwargs["id"], "limit": 500, "offset": kwargs["offset"], "extra": "albums"}
        elif epoint == "label/get":
            params = {"label_id": kwargs["id"], "limit": 500, "offset": kwargs["offset"], "extra": "albums"}
        elif epoint == "favorite/getUserFavorites":
            unix = time.time()
            r_sig = "favoritegetUserFavorites" + str(unix) + kwargs["sec"]
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {"app_id": self.id, "user_auth_token": self.uat, "type": "albums", "request_ts": unix, "request_sig": r_sig_hashed}
        elif epoint == "track/getFileUrl":
            unix = time.time()
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (5, 6, 7, 27):
                raise InvalidQuality("画质 ID 无效")
            r_sig = "trackgetFileUrlformat_id{}intentstreamtrack_id{}{}{}".format(fmt_id, track_id, unix, kwargs.get("sec", self.sec))
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {"request_ts": unix, "request_sig": r_sig_hashed, "track_id": track_id, "format_id": fmt_id, "intent": "stream"}
        else:
            params = kwargs

        has_proxy_pool = bool(self.proxy_list)
        if has_proxy_pool:
            attempt_queue = random.sample(self.proxy_list, len(self.proxy_list))
        else:
            attempt_queue = [None] * 3

        last_error = None
        for i, current_proxy in enumerate(attempt_queue):
            if current_proxy:
                self.base = f"{current_proxy}/api.json/0.2/"
                proxy_display = current_proxy.split("//")[-1]
            else:
                if "qobuz.com" not in self.base and not self.proxy_list:
                    self.base = "https://www.qobuz.com/api.json/0.2/"
                proxy_display = "Direct/Default"
            try:
                r = self.session.get(self.base + epoint, params=params, timeout=10)
                if epoint == "user/login":
                    if r.status_code == 401:
                        raise AuthenticationError("登录失败：Token 无效或过期。\n" + RESET)
                    if r.status_code == 400:
                        raise InvalidAppIdError("API 错误：无效的 App ID。\n" + RESET)
                    console.print(f"[{C_OK}]登录成功！[/{C_OK}]")
                elif epoint in ["track/getFileUrl", "favorite/getUserFavorites"] and r.status_code == 400:
                    raise InvalidAppSecretError(f"API 签名错误 (App Secret 可能已失效): {r.json()}.\n" + RESET)
                elif r.status_code == 401 and epoint in ["track/getFileUrl", "favorite/getUserFavorites"]:
                    # 401 + 签名端点 = 签名有效、仅缺用户 token(test_secret 场景)。
                    # 不能 raise_for_status 吞掉 —— 直接返回,由调用方判定。
                    return r.json()
                r.raise_for_status()
                return r.json()
            except (AuthenticationError, InvalidAppIdError, InvalidAppSecretError):
                raise
            except (requests.exceptions.ProxyError, requests.exceptions.SSLError) as e:
                last_error = requests.exceptions.ProxyError(f"proxy failure via {proxy_display}: {e}")
                if has_proxy_pool:
                    console.print(f"[{C_WARN}]⚡ 代理节点异常，切换下一节点... ({i+1}/{len(attempt_queue)})[/{C_WARN}]")
                elif "search" not in epoint:
                    console.print(f"[{C_WARN}]网络异常，正在重试... ({i+1}/{len(attempt_queue)})[/{C_WARN}]")
            except requests.exceptions.Timeout as e:
                last_error = requests.exceptions.Timeout(f"network timeout via {proxy_display}: {e}")
                if "search" not in epoint:
                    console.print(f"[{C_WARN}]网络超时，正在重试... ({i+1}/{len(attempt_queue)})[/{C_WARN}]")
            except requests.exceptions.RequestException as e:
                last_error = e
                if current_proxy:
                    console.print(f"[{C_WARN}]⚡ 节点 {proxy_display} 异常，切换下一节点... ({i+1}/{len(attempt_queue)})[/{C_WARN}]")
                elif "search" not in epoint:
                    console.print(f"[{C_WARN}]请求失败，正在重试... ({i+1}/{len(attempt_queue)})[/{C_WARN}]")
            if i < len(attempt_queue) - 1:
                time.sleep(1)
        raise last_error

    def auth(self, email, pwd, use_token, user_id, user_auth_token):
        usr_info = self.api_call("user/login", email=email, pwd=pwd, use_token=use_token, user_id=user_id, user_auth_token=user_auth_token)
        user = usr_info.get("user", {})
        credential = user.get("credential", {})
        parameters = credential.get("parameters")
        if not parameters:
            self.label = "Free/Unknown"
            if not usr_info.get("user_auth_token"):
                 raise IneligibleError("您的账户似乎不是付费订阅账户，且未获取到有效 Token。")
        else:
            self.label = parameters.get("short_label", "Unknown")
        self.uat = usr_info.get("user_auth_token")
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        sub = user.get("subscription")
        if sub and sub.get("end_date"):
            try:
                self.expiry_date = date.fromisoformat(sub["end_date"])
                date_str = date.strftime(self.expiry_date, '%Y年%m月%d日')
            except (ValueError, TypeError): date_str = "未知日期"
        else: date_str = "无活跃订阅"
        self.account_meta = {
            'label': self.label,
            'expiry_date': self.expiry_date.isoformat() if hasattr(self, 'expiry_date') else '',
            'region': user.get('country_code', '') or user.get('country', '') or '',
            'status': '可用',
            'status_detail': '',
        }
        console.print(f"[{C_OK}]会员类型: {self.label} | 到期时间: {date_str}[/{C_OK}]")

    def search(self, query, type, limit=10, offset=0):
        # 增加 offset 参数
        # Qobuz API expects plural: tracks/albums/artists/articles/playlists...
        t = (type or "").strip().lower()
        mapping = {
            "track": "tracks",
            "album": "albums",
            "artist": "artists",
            "playlist": "playlists",
        }
        t = mapping.get(t, t)
        return self.api_call("catalog/search", query=query, type=t, limit=limit, offset=offset)

    def multi_meta(self, epoint, key, id, type):
        total = 1
        offset = 0
        while total > 0:
            if type in ["tracks", "albums"]: j = self.api_call(epoint, id=id, offset=offset, type=type)[type]
            else: j = self.api_call(epoint, id=id, offset=offset, type=type)
            if offset == 0:
                yield j
                total = j[key] - 500
            else:
                yield j
                total -= 500
            offset += 500

    def get_album_meta(self, id): return self.api_call("album/get", id=id)
    def get_track_meta(self, id): return self.api_call("track/get", id=id)
    def get_track_url(self, id, fmt_id): return self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)
    def get_artist_meta(self, id): return self.multi_meta("artist/get", "albums_count", id, None)
    def get_plist_meta(self, id): return self.multi_meta("playlist/get", "tracks_count", id, None)
    def get_label_meta(self, id): return self.multi_meta("label/get", "albums_count", id, None)
    
    def test_secret(self, sec):
        # BAD_SIG = secret 错误，返回 False
        # 401 (无 token) = 此时还没登录, 不应该阻障 login
        # 网络错误 / timeout = 一律当作 unknown, 返回 False (保守)
        try:
            self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=sec)
            return True
        except InvalidAppSecretError:
            return False
        except (AuthenticationError, requests.exceptions.HTTPError, requests.exceptions.RequestException):
            return False

    def cfg_setup(self):
        # _pre_fetch_credentials 已完成凭据验证，这里做兜底
        if self.sec is None:
            for secret in self.secrets:
                if not secret: continue
                if self.test_secret(secret):
                    self.sec = secret
                    break
        if self.sec is None:
            raise InvalidAppSecretError("无法找到有效的 App Secret，Qobuz 可能更新了加密算法。\n" + RESET)
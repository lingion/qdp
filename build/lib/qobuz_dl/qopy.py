import hashlib
import logging
import time
import random
from datetime import date
import requests
from qobuz_dl.exceptions import (
    AuthenticationError, IneligibleError, InvalidAppIdError, 
    InvalidAppSecretError, InvalidQuality
)
from qobuz_dl.utils import get_api_base_url, get_proxy_list
from rich.console import Console

console = Console()
RESET = "请运行 'qd -r' 重置凭证"
logger = logging.getLogger(__name__)

# 莫兰迪配色
C_TEXT = "#abb2bf"
C_OK   = "#98c379"
C_WARN = "#e5c07b"
C_ERR  = "#e06c75"

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
        self.auth(email, pwd, use_token, user_id, user_auth_token)
        self.cfg_setup()

    def api_call(self, epoint, **kwargs):
        # 1. 准备请求参数
        if epoint == "catalog/search":
            params = {
                "query": kwargs["query"],
                "limit": kwargs["limit"],
                "type": kwargs["type"],
                "offset": kwargs.get("offset", 0)  # <--- 核心修复：加上偏移量参数
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
        
        # --- 2. 构建重试队列 ---
        if self.proxy_list and len(self.proxy_list) > 0:
            attempt_queue = random.sample(self.proxy_list, len(self.proxy_list))
        else:
            attempt_queue = [None] * 3 

        last_error = None
        
        # --- 3. 循环尝试 ---
        for i, current_proxy in enumerate(attempt_queue):
            if current_proxy:
                self.base = f"{current_proxy}/api.json/0.2/"
                proxy_display = current_proxy.split('//')[-1]
            else:
                if "qobuz.com" not in self.base and not self.proxy_list:
                    self.base = "https://www.qobuz.com/api.json/0.2/"
                proxy_display = "Direct/Default"

            try:
                r = self.session.get(self.base + epoint, params=params, timeout=10)
                
                if epoint == "user/login":
                    if r.status_code == 401: raise AuthenticationError("登录失败：Token 无效或过期。\n" + RESET)
                    elif r.status_code == 400: raise InvalidAppIdError("API 错误：无效的 App ID。\n" + RESET)
                    else: console.print(f"[{C_OK}]登录成功！[/{C_OK}]")
                elif epoint in ["track/getFileUrl", "favorite/getUserFavorites"] and r.status_code == 400:
                    raise InvalidAppSecretError(f"API 签名错误 (App Secret 可能已失效): {r.json()}.\n" + RESET)

                r.raise_for_status()
                return r.json()

            except (requests.exceptions.RequestException, requests.exceptions.SSLError) as e:
                last_error = e
                retry_msg = f"({i+1}/{len(attempt_queue)})"
                if current_proxy:
                    console.print(f"[{C_WARN}]⚡ 节点 {proxy_display} 异常，切换下一节点... {retry_msg}[/{C_WARN}]")
                else:
                    # 如果是搜索超时，静默重试，不打印太多干扰信息
                    if "search" not in epoint:
                        console.print(f"[{C_WARN}]请求失败，正在重试... {retry_msg}[/{C_WARN}]")
                
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
        console.print(f"[{C_OK}]会员类型: {self.label} | 到期时间: {date_str}[/{C_OK}]")

    def search(self, query, type, limit=10, offset=0):
        # 增加 offset 参数
        return self.api_call("catalog/search", query=query, type=type, limit=limit, offset=offset)

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
        try:
            self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=sec)
            return True
        except InvalidAppSecretError: return False

    def cfg_setup(self):
        for secret in self.secrets:
            if not secret: continue
            if self.test_secret(secret):
                self.sec = secret
                break
        if self.sec is None:
            raise InvalidAppSecretError("无法找到有效的 App Secret，Qobuz 可能更新了加密算法。\n" + RESET)
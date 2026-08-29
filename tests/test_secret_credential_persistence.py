"""Secret 判定与持久化行为测试。

背景(2026-08 修复的三个问题):
1. test_secret 把「签名有效、仅缺用户 token 的 401」当失败 — 有效 secret 被误判失效,
   导致每次启动都重新爬 web player。
2. 自动爬取到的 secret 只存在内存(_auto_fetched_credentials 无消费方),从不落盘,
   下次启动又要爬。
3. 落盘时必须同步到 active account section,否则下次切号/读 account 时又回到旧 secret。
"""

import configparser
import os
import tempfile
import unittest
from unittest.mock import patch

from qdp import config as qdp_config
from qdp import qopy
from qdp.accounts import load_account_config
from qdp.exceptions import InvalidAppSecretError


def _make_client(secrets, app_id="950096963"):
    """构造绕过网络登录的 Client 骨架,只测 secret 判定逻辑。"""
    import requests

    cl = qopy.Client.__new__(qopy.Client)
    cl.secrets = list(secrets)
    cl.id = str(app_id)
    cl.sec = None
    cl._auto_fetched_credentials = False
    cl.session = requests.Session()
    cl.session.headers.update({"X-App-Id": cl.id})
    cl.proxy_list = []
    cl.base = "https://www.qobuz.com/api.json/0.2/"
    return cl


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Error", response=self
            )


class TestSecretJudgement(unittest.TestCase):
    """test_secret 的 401 语义:签名有效只差用户 token → 应视为有效。"""

    def test_401_unauthenticated_means_signature_valid(self):
        """401 = 签名通过、服务器先要求用户认证 → secret 有效,返回 True。

        走真实 api_call(仅 mock HTTP 层),确保 401 分支在代理轮询内被正确处理。
        """
        cl = _make_client(["goodsecret"])
        with patch.object(
            cl.session, "get",
            return_value=_FakeResponse(
                401, {"code": 401, "message": "User authentication is required"}
            ),
        ):
            self.assertTrue(cl.test_secret("goodsecret"))

    def test_bad_signature_still_means_invalid_secret(self):
        """真·签名错误(BAD_SIG)→ secret 无效,返回 False。"""
        cl = _make_client(["badsecret"])
        with patch.object(
            cl, "api_call", side_effect=InvalidAppSecretError("API 签名错误")
        ):
            self.assertFalse(cl.test_secret("badsecret"))

    def test_network_error_returns_false(self):
        """网络异常保守判无效,不崩溃。"""
        import requests

        cl = _make_client(["whatever"])
        with patch.object(
            cl, "api_call", side_effect=requests.exceptions.Timeout("timeout")
        ):
            self.assertFalse(cl.test_secret("whatever"))


class TestCredentialPersistence(unittest.TestCase):
    """自动爬取的凭据必须落盘 config + 同步 active account。"""

    def test_persist_writes_config_and_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write(
                    "[DEFAULT]\n"
                    "app_id = 111111111\n"
                    "secrets = oldsecret\n"
                    "active_account = myacc\n"
                    "\n"
                    "[account:myacc]\n"
                    "app_id = 111111111\n"
                    "secrets = oldsecret\n"
                    "account_name = myacc\n"
                )

            cl = _make_client(["oldsecret"])
            cl.persist_credentials(new_app_id="222222222", new_secrets=["newsecret"],
                                   config_file=cfg_file)

            # config DEFAULT 更新
            check = configparser.ConfigParser()
            check.read(cfg_file)
            self.assertEqual(check["DEFAULT"]["app_id"], "222222222")
            self.assertEqual(check["DEFAULT"]["secrets"], "newsecret")
            # active account section 同步
            self.assertEqual(check["account:myacc"]["app_id"], "222222222")
            self.assertEqual(check["account:myacc"]["secrets"], "newsecret")
            # load_account_config 读到新值
            loaded = load_account_config(cfg_file, env={})
            self.assertEqual(loaded.app_id, "222222222")
            self.assertEqual(loaded.secrets, ("newsecret",))

    def test_persist_without_account_section_only_updates_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write("[DEFAULT]\napp_id = 111111111\nsecrets = oldsecret\n")

            cl = _make_client(["oldsecret"])
            cl.persist_credentials(new_app_id="222222222", new_secrets=["a", "b"],
                                   config_file=cfg_file)

            check = configparser.ConfigParser()
            check.read(cfg_file)
            self.assertEqual(check["DEFAULT"]["app_id"], "222222222")
            self.assertEqual(check["DEFAULT"]["secrets"], "a,b")

    def test_persist_never_touches_auth_fields(self):
        """落盘只允许改 app_id/secrets,严禁碰 email/password/token 等账号字段。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write(
                    "[DEFAULT]\n"
                    "app_id = 111111111\n"
                    "secrets = oldsecret\n"
                    "user_auth_token = keepme\n"
                    "password = keepme2\n"
                    "active_account = acc1\n"
                    "\n"
                    "[account:acc1]\n"
                    "secrets = oldsecret\n"
                    "user_auth_token = keepme3\n"
                )

            cl = _make_client(["oldsecret"])
            cl.persist_credentials(new_app_id="222222222", new_secrets=["ns"],
                                   config_file=cfg_file)

            check = configparser.ConfigParser()
            check.read(cfg_file)
            self.assertEqual(check["DEFAULT"]["user_auth_token"], "keepme")
            self.assertEqual(check["DEFAULT"]["password"], "keepme2")
            self.assertEqual(check["account:acc1"]["user_auth_token"], "keepme3")

    def test_pre_fetch_persists_auto_fetched_credentials(self):
        """_pre_fetch_credentials 爬取成功 → 自动落盘。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write("[DEFAULT]\napp_id = 111111111\nsecrets = deadbeef\n")

            cl = _make_client(["deadbeef"])
            with patch.object(cl, "test_secret", side_effect=[False, True]), \
                 patch("qdp.qopy.fetch_web_player_credentials",
                       return_value=("222222222", ["fresh", "alsofresh"])), \
                 patch.object(cl, "persist_credentials") as persist_mock:
                cl._pre_fetch_credentials(config_file=cfg_file)

            persist_mock.assert_called_once_with(
                new_app_id="222222222",
                new_secrets=["fresh"],
                config_file=cfg_file,
            )
            self.assertTrue(cl._auto_fetched_credentials)

    def test_pre_fetch_switches_app_id_before_testing_secrets(self):
        """爬取的 app_id 与 config 不同 → 必须先切 app_id 再测 secret。

        secret 签名依赖 X-App-Id header;旧 app_id + 新 secret 会被 API 以
        400 拒绝,导致"获取到 N 个 secret 但均验证失败"。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write("[DEFAULT]\napp_id = 111111111\nsecrets = deadbeef\n")

            cl = _make_client(["deadbeef"], app_id="111111111")
            tested_under = []

            def fake_test(sec):
                # 只记录 auto secret 的测试(config secret "deadbeef" 也会被测,跳过)
                if sec != "deadbeef":
                    tested_under.append(cl.id)  # 记录测试时生效的 app_id
                return sec == "fresh"

            with patch.object(cl, "test_secret", side_effect=fake_test), \
                 patch("qdp.qopy.fetch_web_player_credentials",
                       return_value=("222222222", ["fresh"])):
                cl._pre_fetch_credentials(config_file=cfg_file)

            self.assertEqual(tested_under, ["222222222"])  # 先切 app_id
            self.assertEqual(cl.sec, "fresh")
            self.assertEqual(cl.id, "222222222")

    def test_pre_fetch_restores_app_id_when_all_secrets_fail(self):
        """全部 auto secret 失败 → 还原原 app_id,走配置兜底。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "config.ini")
            with open(cfg_file, "w", encoding="utf-8") as fp:
                fp.write("[DEFAULT]\napp_id = 111111111\nsecrets = deadbeef\n")

            cl = _make_client(["deadbeef"], app_id="111111111")
            with patch.object(cl, "test_secret", return_value=False), \
                 patch("qdp.qopy.fetch_web_player_credentials",
                       return_value=("222222222", ["bad1", "bad2"])):
                cl._pre_fetch_credentials(config_file=cfg_file)

            self.assertIsNone(cl.sec)
            self.assertEqual(cl.id, "111111111")  # 还原
            self.assertFalse(cl._auto_fetched_credentials)


if __name__ == "__main__":
    unittest.main()

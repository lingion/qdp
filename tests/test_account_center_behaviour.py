import configparser
import tempfile
import unittest
from unittest.mock import patch

from qdp import accounts, ui


class FakeConsole:
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.index = 0
        self.messages = []

    def clear(self):
        pass

    def print(self, *args, **kwargs):
        self.messages.append(" ".join(str(arg) for arg in args))

    def input(self, prompt=""):
        self.messages.append(prompt)
        if self.index >= len(self.inputs):
            raise AssertionError("No more fake console inputs available")
        value = self.inputs[self.index]
        self.index += 1
        return value


class FakeQobuz:
    def __init__(self, meta):
        self.meta = meta
        self.client = None

    def initialize_client(self, *args, **kwargs):
        self.client = type("Client", (), {"account_meta": self.meta})()


class AccountCenterBehaviourTests(unittest.TestCase):
    def test_initialize_qobuz_client_preserves_existing_non_empty_account_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = f"{tmp}/config.ini"
            config = configparser.ConfigParser()
            config["DEFAULT"] = {
                "active_account": "acc1",
                "email": "user@example.com",
                "password": "pw",
                "app_id": "app",
                "secrets": "sec",
                "use_token": "false",
                "user_id": "",
                "user_auth_token": "",
                "region": "JP",
                "expiry_date": "2030-01-01",
                "label": "Family",
            }
            config["account:acc1"] = {
                "email": "user@example.com",
                "password": "pw",
                "app_id": "app",
                "secrets": "sec",
                "use_token": "false",
                "region": "JP",
                "expiry_date": "2030-01-01",
                "label": "Family",
            }
            with open(config_path, "w", encoding="utf-8") as fp:
                config.write(fp)

            defaults = dict(config["DEFAULT"])
            qobuz = FakeQobuz({
                "region": "",
                "expiry_date": "",
                "label": "",
                "status": "可用",
                "status_detail": "",
            })

            with patch("qdp.ui.CONFIG_FILE", config_path):
                ui.initialize_qobuz_client(qobuz, defaults)

            updated = accounts._load_config(config_path)
            self.assertEqual(defaults["region"], "JP")
            self.assertEqual(defaults["expiry_date"], "2030-01-01")
            self.assertEqual(defaults["label"], "Family")
            self.assertEqual(updated["account:acc1"]["region"], "JP")
            self.assertEqual(updated["account:acc1"]["expiry_date"], "2030-01-01")
            self.assertEqual(updated["account:acc1"]["label"], "Family")
            self.assertEqual(updated["account:acc1"]["status"], "可用")

    def test_account_center_test_all_iterates_every_account_with_progress_and_stays_inside(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = f"{tmp}/config.ini"
            accounts.create_account_record("acc1", {
                "use_token": "false",
                "email": "a1@example.com",
                "password": "pw1",
                "app_id": "app",
                "secrets": "sec",
                "region": "US",
            }, config_path)
            accounts.create_account_record("acc2", {
                "use_token": "false",
                "email": "a2@example.com",
                "password": "pw2",
                "app_id": "app",
                "secrets": "sec",
                "region": "JP",
            }, config_path)
            accounts.switch_account("acc1", config_path)
            defaults = ui.load_config_defaults(config_path)
            console = FakeConsole(["T", "", "b"])

            with patch("qdp.ui.CONFIG_FILE", config_path), \
                 patch("qdp.ui.build_qobuz_from_defaults", side_effect=lambda defaults: FakeQobuz({
                     "region": "",
                     "expiry_date": "",
                     "label": "",
                     "status": "可用",
                     "status_detail": "",
                 })), \
                 patch("qdp.ui._header", lambda *args, **kwargs: None):
                changed = ui._ui_account_center(console, defaults)

            self.assertTrue(changed)
            self.assertEqual(console.index, 3)
            joined = "\n".join(console.messages)
            self.assertIn("1/2: 正在测试账号: acc1", joined)
            self.assertIn("2/2: 正在测试账号: acc2", joined)
            self.assertIn("全部账号测试完成", joined)
            active = accounts.get_active_account(config_path)
            self.assertEqual(active, "acc1")


if __name__ == "__main__":
    unittest.main()

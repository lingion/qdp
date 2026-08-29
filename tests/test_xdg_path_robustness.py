"""XDG/HOME/APPDATA 路径解析健壮性测试。

审计发现(P2): config.py/utils.py 用 os.environ["HOME"], HOME 未设时
import 即 KeyError; accounts.py/server.py 用 expanduser 兜底, 五处解析
行为不一致。
"""
import os
import unittest
from unittest.mock import patch


class XdgPathRobustnessTests(unittest.TestCase):
    def test_config_import_without_home(self):
        """HOME 未设 → from qdp import config 不得崩。"""
        import subprocess
        import sys
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {k: v for k, v in os.environ.items() if k not in ("HOME", "XDG_CONFIG_HOME", "APPDATA")}
        env["PYTHONPATH"] = repo
        result = subprocess.run(
            [sys.executable, "-c", "from qdp import config; print(config.CONFIG_FILE)"],
            env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("config.ini", result.stdout)

    def test_get_config_path_without_home(self):
        from qdp import utils
        env = {k: v for k, v in os.environ.items() if k not in ("HOME", "XDG_CONFIG_HOME")}
        with patch.dict(os.environ, env, clear=True):
            path = utils.get_config_path()
        self.assertTrue(path.endswith("config.ini"))
        self.assertIn("qobuz-dl", path)

    def test_xdg_config_home_respected(self):
        from qdp import utils
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "/custom/xdg"}, clear=False):
            self.assertEqual(utils.get_config_path(), os.path.join("/custom/xdg", "qobuz-dl", "config.ini"))


if __name__ == "__main__":
    unittest.main()

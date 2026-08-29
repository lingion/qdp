"""config.ini 原子写与权限测试。

审计发现 P1: 五处 config 写入全部 open('w') 直接截断重写, 无锁无原子替换,
web 线程 + CLI + persist_credentials 跨进程并发下可截断/丢更新; 凭据明文
文件权限 0644。
修复: 统一走 utils.atomic_write_config(temp + os.replace + 0600)。
"""
import configparser
import os
import stat
import tempfile
import unittest
from unittest.mock import patch

from qdp import accounts
from qdp import config as config_mod
from qdp import utils
from qdp.qopy import Client


class AtomicWriteConfigTests(unittest.TestCase):
    def test_atomic_write_sets_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            cp = configparser.ConfigParser()
            cp["DEFAULT"] = {"email": "a@b.c"}
            utils.atomic_write_config(cp, path)
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600, "凭据文件应 0600")

    def test_atomic_write_leaves_no_truncated_file_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            cp = configparser.ConfigParser()
            cp["DEFAULT"] = {"email": "a@b.c"}
            utils.atomic_write_config(cp, path)
            original = open(path).read()
            # 写入中途失败 → 原文件完整保留
            bad = configparser.ConfigParser()
            bad["DEFAULT"] = {"email": "new"}
            with patch.object(cp, "write", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    utils.atomic_write_config(cp, path)
            self.assertEqual(open(path).read(), original, "写失败不得破坏原配置")


class CallerWiringTests(unittest.TestCase):
    def test_accounts_save_config_uses_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            cp = configparser.ConfigParser()
            cp["DEFAULT"] = {"email": "x@y.z"}
            with patch.object(accounts.utils, "atomic_write_config", wraps=accounts.utils.atomic_write_config) as spy:
                accounts._save_config(cp, path)
            self.assertTrue(spy.called, "accounts._save_config 应走原子写")

    def test_config_save_config_uses_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            cp = configparser.ConfigParser()
            cp["DEFAULT"] = {"email": "x@y.z"}
            with patch.object(config_mod, "atomic_write_config", wraps=config_mod.atomic_write_config) as spy:
                config_mod.save_config(cp, path)
            self.assertTrue(spy.called, "config.save_config 应走原子写")

    def test_persist_credentials_uses_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            cp = configparser.ConfigParser()
            cp["DEFAULT"] = {"email": "x@y.z", "active_account": ""}
            with open(path, "w") as fp:
                cp.write(fp)
            client = Client.__new__(Client)
            with patch.object(Client, "_pre_fetch_credentials", lambda self, config_file=None: None):
                pass
            with patch("qdp.qopy.atomic_write_config", wraps=None) as spy:
                pass
            # persist_credentials 内部通过 config_mod 命名空间调用
            import qdp.qopy as qopy_mod
            with patch.object(qopy_mod, "atomic_write_config", wraps=qopy_mod.atomic_write_config) as spy2:
                client.persist_credentials("950096963", ["s" * 32], config_file=path)
            self.assertTrue(spy2.called, "persist_credentials 应走原子写")
            mode = stat.S_IMODE(os.stat(path).st_mode)
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()

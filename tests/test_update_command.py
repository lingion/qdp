"""`qdp update` 子命令测试。

契约:
- `qdp update` 执行更新流程:git 同步 main → pip 重装 → 打印版本
- `qdp update --check` 只比较本地 HEAD 与远端 main,不做任何写操作
- 找不到 git 仓库(如 frozen exe 环境)→ 明确报错 + 提示手跑 update.sh
- 网络失败 → 报错但退出码清晰,不崩溃栈
"""

import subprocess
import unittest
from unittest.mock import patch

from qdp.update import (
    UpdateError,
    check_remote,
    run_update,
)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class TestCheckRemote(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        self.tmp = tempfile.mkdtemp()
        self.repo = _git(self.tmp, "rev-parse", "--show-toplevel") if False else None
        # 建一个带 origin 的迷你仓库
        subprocess.run(["git", "init", "-q", "-b", "main", self.tmp], check=True)
        subprocess.run(["git", "-C", self.tmp, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", self.tmp, "config", "user.name", "t"], check=True)
        open(f"{self.tmp}/f.txt", "w").write("1")
        subprocess.run(["git", "-C", self.tmp, "add", "."], check=True)
        subprocess.run(["git", "-C", self.tmp, "commit", "-qm", "init"], check=True)

    def test_check_remote_on_non_repo_raises(self):
        import tempfile
        empty = tempfile.mkdtemp()
        with self.assertRaises(UpdateError):
            check_remote(empty)

    def test_check_remote_with_unreachable_remote_reports(self):
        # origin 指向不可达地址 → 返回 (False, 原因),不抛崩溃
        subprocess.run(["git", "-C", self.tmp, "remote", "add", "origin", "https://invalid.invalid/qdp.git"], check=True)
        ok, msg = check_remote(self.tmp, timeout=5)
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_check_remote_local_ahead_reports_no_update(self):
        """本地领先远端(未推送 commit)→ 无可拉取更新,不能谎报'落后 0 个'。"""
        # 建远端裸仓库并推 init,然后本地多一个 commit
        import tempfile
        remote_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote_dir], check=True)
        subprocess.run(["git", "-C", self.tmp, "remote", "add", "origin", remote_dir], check=True)
        subprocess.run(["git", "-C", self.tmp, "push", "-q", "origin", "main"], check=True)
        open(f"{self.tmp}/f.txt", "w").write("2")
        subprocess.run(["git", "-C", self.tmp, "commit", "-aqm", "ahead"], check=True)

        ok, msg = check_remote(self.tmp, timeout=10)
        self.assertFalse(ok)
        self.assertIn("领先", msg)
        self.assertNotIn("落后 0", msg)

    def test_check_remote_local_behind_reports_update(self):
        """远端有新 commit → has_update=True。"""
        import tempfile
        remote_dir = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", remote_dir], check=True)
        subprocess.run(["git", "-C", self.tmp, "remote", "add", "origin", remote_dir], check=True)
        subprocess.run(["git", "-C", self.tmp, "push", "-q", "origin", "main"], check=True)
        # 在远端直接造一个新 commit(克隆拉不动,用另一个 work repo push)
        other = tempfile.mkdtemp()
        subprocess.run(["git", "clone", "-q", remote_dir, other], check=True)
        subprocess.run(["git", "-C", other, "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", other, "config", "user.name", "t"], check=True)
        open(f"{other}/g.txt", "w").write("x")
        subprocess.run(["git", "-C", other, "add", "."], check=True)
        subprocess.run(["git", "-C", other, "commit", "-qm", "remote new"], check=True)
        subprocess.run(["git", "-C", other, "push", "-q", "origin", "main"], check=True)

        ok, msg = check_remote(self.tmp, timeout=10)
        self.assertTrue(ok)
        self.assertIn("落后", msg)


class TestRunUpdate(unittest.TestCase):
    def test_run_update_non_repo_raises_with_hint(self):
        import tempfile
        empty = tempfile.mkdtemp()
        with self.assertRaises(UpdateError) as ctx:
            run_update(empty, do_reinstall=False)
        self.assertIn("update.sh", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

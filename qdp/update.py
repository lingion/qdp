"""qdp update — 自更新流程。

`qdp update`        : git 同步 origin/main → pip 重装(editable) → 打印版本
`qdp update --check`: 只比较本地与远端,不写任何东西

设计要点:
- 纯 Python 跨平台(macOS/Linux/Termux/WSL/Git Bash),替代 bash update.sh 入口
- git 不可用或网络失败时,给出 update.sh 手动兜底提示
- 退出码:0 成功 / 1 可预期失败(UpdateError)
"""

import logging
import os
import shutil
import subprocess
import sys

from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()

C_OK = "#98c379"
C_WARN = "#e5c07b"
C_ERR = "#e06c75"
C_TEXT = "#abb2bf"

# update.sh 的手动兜底入口,失败时提示用户
UPDATE_SH_URL = "https://raw.githubusercontent.com/lingion/qdp/main/update.sh"


class UpdateError(Exception):
    """可预期的更新失败(带用户可读信息)。"""


def _run(cmd, cwd=None, timeout=60):
    """跑子进程,返回 (returncode, stdout+stderr)。"""
    env = dict(os.environ)
    # git 输出中文化会影响断言,强制英文;同时避免 pip/git 交互提示
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"


def _find_qdp_dir():
    """定位 qdp 源码目录:从本模块位置向上找包含 setup.py 的仓库根。"""
    here = os.path.dirname(os.path.abspath(__file__))  # <repo>/qdp/
    repo_root = os.path.dirname(here)
    if os.path.isfile(os.path.join(repo_root, "setup.py")) and os.path.isdir(os.path.join(repo_root, ".git")):
        return repo_root
    # pip editable 安装场景同样满足上面的路径结构;
    # frozen exe / pip site-packages 安装则没有 .git
    if os.path.isfile(os.path.join(repo_root, "setup.py")):
        return repo_root
    raise UpdateError(
        "找不到 qdp 源码仓库(需要 setup.py + git)。\n"
        f"手动更新: curl -fsSL {UPDATE_SH_URL} | bash"
    )


def check_remote(qdp_dir=None, timeout=30):
    """比较本地 HEAD 与远端 main。

    Returns:
        tuple: (has_update: bool, message: str)
    Raises:
        UpdateError: 不在 git 仓库内时。
    """
    qdp_dir = qdp_dir or _find_qdp_dir()
    rc, out = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=qdp_dir)
    if rc != 0 or out.strip() != "true":
        raise UpdateError("当前 qdp 不是 git 仓库克隆,无法自动更新。\n"
                          f"手动更新: curl -fsSL {UPDATE_SH_URL} | bash")

    rc, out = _run(["git", "fetch", "origin", "main"], cwd=qdp_dir, timeout=timeout)
    if rc != 0:
        return False, f"git fetch 失败(网络?): {out.strip().splitlines()[-1] if out.strip() else 'unknown'}"

    local = _git_rev(qdp_dir, "HEAD")
    remote = _git_rev(qdp_dir, "origin/main")
    if not local or not remote:
        return False, "无法读取 commit hash"

    if local == remote:
        return False, f"已是最新 ({local[:8]})"

    ahead_rc, ahead_out = _run(["git", "rev-list", "--count", f"{remote}..{local}"], cwd=qdp_dir)
    behind_rc, behind_out = _run(["git", "rev-list", "--count", f"{local}..{remote}"], cwd=qdp_dir)
    ahead = ahead_out.strip() if ahead_rc == 0 else "?"
    behind = behind_out.strip() if behind_rc == 0 else "?"

    if behind == "0":
        # 本地领先(未 push 的 commit),没有可拉取的更新
        return False, f"本地 {local[:8]} 领先远端 {ahead} 个 commit (未推送),无可拉取更新"
    if ahead == "0":
        return True, f"有新版本!本地 {local[:8]} 落后远端 {behind} 个 commit (远端 {remote[:8]})"
    return True, f"本地与远端分叉:本地领先 {ahead} / 落后 {behind} 个 commit (远端 {remote[:8]})"


def _git_rev(qdp_dir, ref):
    rc, out = _run(["git", "rev-parse", ref], cwd=qdp_dir)
    return out.strip() if rc == 0 else ""


def _has_local_changes(qdp_dir):
    rc, out = _run(["git", "status", "--porcelain"], cwd=qdp_dir)
    return rc == 0 and bool(out.strip())


def sync_code(qdp_dir, timeout=120):
    """git 同步 origin/main(ff-only,防本地改动搅局)。

    本地有未提交修改时先 stash,merge 成功后 pop 恢复。
    """
    stashed = False
    if _has_local_changes(qdp_dir):
        console.print(f"[{C_WARN}]检测到本地未提交修改,先 stash 保护…[/{C_WARN}]")
        rc, out = _run(["git", "stash", "push", "-m", "qdp update auto-stash"], cwd=qdp_dir, timeout=30)
        if rc != 0:
            raise UpdateError(f"git stash 失败,请手动处理本地修改:\n{out.strip()}")
        stashed = True

    rc, out = _run(["git", "fetch", "origin", "main"], cwd=qdp_dir, timeout=timeout)
    if rc != 0:
        raise UpdateError(f"git fetch 失败(检查网络/镜像可达性):\n{out.strip()}")

    rc, out = _run(["git", "merge", "origin/main", "--ff-only"], cwd=qdp_dir, timeout=timeout)
    if rc != 0:
        if stashed:
            _run(["git", "stash", "pop"], cwd=qdp_dir, timeout=30)
        raise UpdateError(f"git merge --ff-only 失败(本地历史分叉?):\n{out.strip()}")

    if stashed:
        rc, out = _run(["git", "stash", "pop"], cwd=qdp_dir, timeout=30)
        if rc != 0:
            console.print(f"[{C_WARN}]stash pop 有冲突,你的本地修改保存在 stash 里: git stash pop[/{C_WARN}]")
        else:
            console.print(f"[{C_TEXT}]本地修改已恢复(stash pop)[/{C_TEXT}]")

    new_head = _git_rev(qdp_dir, "HEAD")
    console.print(f"[{C_OK}]代码已同步到 {new_head[:8]}[/{C_OK}]")
    return new_head


def reinstall(qdp_dir, timeout=300):
    """在源码目录重装 editable 包(立即生效)。"""
    pip_candidates = [
        os.path.join(qdp_dir, ".venv", "bin", "pip"),
        os.path.join(qdp_dir, ".venv", "Scripts", "pip.exe"),  # Windows
    ]
    pip_cmd = None
    for cand in pip_candidates:
        if os.path.isfile(cand):
            pip_cmd = [cand]
            break
    if pip_cmd is None:
        python = sys.executable or "python3"
        pip_cmd = [python, "-m", "pip"]

    console.print(f"[{C_TEXT}]重新安装 qdp (editable)…[/{C_TEXT}]")
    rc, out = _run(pip_cmd + ["install", "-e", ".", "--quiet", "--no-build-isolation"],
                   cwd=qdp_dir, timeout=timeout)
    if rc != 0:
        raise UpdateError(f"pip install 失败:\n{out.strip()[-500:]}")
    console.print(f"[{C_OK}]包已重装[/{C_OK}]")


def run_update(qdp_dir=None, do_reinstall=True):
    """执行完整更新流程。返回退出码。"""
    qdp_dir = qdp_dir or _find_qdp_dir()
    console.print(f"[{C_TEXT}]qdp 目录: {qdp_dir}[/{C_TEXT}]")

    rc, out = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=qdp_dir)
    if rc != 0 or out.strip() != "true":
        raise UpdateError(
            f"{qdp_dir} 不是 git 仓库克隆,无法自动更新。\n"
            f"手动更新: curl -fsSL {UPDATE_SH_URL} | bash"
        )

    sync_code(qdp_dir)

    if do_reinstall:
        reinstall(qdp_dir)

    # 打印新版本
    rc, out = _run([sys.executable or "python3", "-c", "import qdp; print(qdp.__version__)"],
                   cwd=qdp_dir, timeout=30)
    version = out.strip() if rc == 0 else "?"
    console.print(f"[{C_OK}]更新完成!当前版本: qdp {version}[/{C_OK}]")
    return 0

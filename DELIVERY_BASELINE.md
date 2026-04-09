# Sprint 1 Delivery Baseline

## 交付目录
- 独立交付目录：`/Users/lingion/Documents/qdp-main-github-delivery`
- 原始参考目录（只读盘点，不作为主要写入目标）：`/Users/lingion/Documents/qdp-main`
- 备份参考目录（只读盘点，不直接整包恢复）：`/Users/lingion/Documents/qdp-main_backup_20260408_183623`

## Sprint 1 目标
本冲刺只建立 GitHub 交付工作区基线：
- 先盘点现有入口、依赖文件、文档与部署候选
- 建立新的独立交付目录
- 定义复制/排除规则
- 明确后续整理只能在新目录中进行，避免污染原始仓库

## 盘点摘要

### 1. 入口
- CLI / TUI 入口：`python -m qdp`、`qdp`
- CLI 实现：`qdp/__main__.py`、`qdp/cli.py`
- 交互式 UI/TUI：`qdp/ui.py`
- Web Runtime 入口：`python -m qdp.web.server`
- Web 服务实现：`qdp/web/server.py`
- 前端静态资源：`qdp/web/app/`

### 2. 依赖与发布相关文件
- 运行依赖：`requirements.txt`
- 构建依赖：`requirements-build.txt`
- 发布配置：`setup.py`
- PyInstaller 配置：`qdp.spec`
- 启动/构建脚本：`build_windows.sh`、`build_windows.bat`、`build_windows.ps1`
- 测试配置：`pytest.ini`

### 3. 文档现状
- 项目总说明：`README.md`
- 升级说明：`UPGRADE_NOTES.md`
- 项目文档目录：`docs/`
- 当前 README 已覆盖项目概述、安装、运行、测试、打包与环境变量，但原始仓库仍混有明显本地产物，因此需要先建立干净交付目录。

### 4. 部署/运行方式候选
- 本地 CLI/TUI 运行：`python -m qdp` 或 `qdp`
- 本地 Web Runtime：`python -m qdp.web.server`
- 本地测试验证：`pytest -q`
- 本地 smoke 验证：`python3 scripts/webplayer_smoke.py --json`
- 本地 PyInstaller 打包候选：`python -m PyInstaller --clean --noconfirm qdp.spec`

### 5. 参考备份来源
- 参考备份目录：`/Users/lingion/Documents/qdp-main_backup_20260408_183623`
- 备份目录用途：用于对照是否存在可恢复但缺失的发布文件或文档，不作为本冲刺的整包复制来源。

## 复制规则（纳入新交付目录）
保留当前项目的核心源码与文档骨架：
- `qdp/`
- `tests/`
- `docs/`
- `scripts/`
- `README.md`
- `requirements.txt`
- `requirements-build.txt`
- `setup.py`
- `pytest.ini`
- `qdp.spec`
- `qdp_pyinstaller_entry.py`
- `build_windows.*`
- `.gitignore`
- `.env.example`
- `LICENSE`
- `UPGRADE_NOTES.md`

## 排除规则（不纳入 GitHub 交付目录）
以下内容判定为本地产物、缓存、备份或临时归档，Sprint 1 交付目录中排除：
- `.pytest_cache/`
- `.venv-build/`
- `Qobuz Downloads/`
- `backups/`
- `.backup-webplayer/`
- `__pycache__/`
- `*.pyc`
- `.DS_Store`
- 临时备份归档文件（如 `.tgz`、`.zip`、`.bak`）

## 只写新目录策略
- 从 Sprint 1 开始，后续整理、文档补齐、忽略规则治理、验证记录与打包动作都应以本交付目录为唯一主要写入目标。
- `/Users/lingion/Documents/qdp-main` 与备份目录仅用于只读盘点、对照与必要恢复判断。
- 如需新增交付文档、忽略规则或修复发布结构，统一落在 `/Users/lingion/Documents/qdp-main-github-delivery`。

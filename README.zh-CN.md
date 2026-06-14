# qdp

qdp 是一个本地 Qobuz 工具箱，提供命令行/TUI 下载工作流和本地网页播放器。

Sprint 1 建立了交付基线，包括范围文档、备份规则、可运行命令和打包元数据。

[English](README.md) | 中文

## 仓库内容
- 命令行入口：`qdp/__main__.py` 和 `qdp/cli.py`
- 交互式 UI/TUI：`qdp/ui.py`
- 账号管理：`qdp/accounts.py`
- 本地网页播放器服务器：`qdp/web/server.py`
- 浏览器应用资源：`qdp/web/app/`
- 自动化测试：`tests/`
- 打包文件：`setup.py`、`qdp.spec`、`build_windows.*`

## 环境要求
- Python 3.9+
- pip
- Qobuz 账号凭证/配置（本地可用）

## 安装
创建虚拟环境并安装运行时依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e . --no-build-isolation
```

## 环境 / 凭证
示例变量见 `.env.example`。

应用也会从本地 qdp 配置流程中读取账号/配置数据，特别是用于已认证的网页播放器操作。

## 运行
### CLI / TUI
```bash
qdp
```

或

```bash
python -m qdp
```

首次配置：

```bash
qdp -r
```

配置向导会引导你完成登录方式、密钥选择（默认安卓密钥/自动抓取网页密钥/手动输入 App ID 和 Secret）、下载目录和音质偏好。

### 快捷命令
```bash
qdp -s "关键词"       # 搜索全部
qdp -sa "专辑名"      # 搜索专辑
qdp -st "曲名"        # 搜索单曲
qdp "https://www.qobuz.com/album/xxxxx"  # 从链接下载
qdp --version          # 显示版本号 (114.0.1)
qdp --help             # 显示帮助（无需配置即可运行）
```

### 网页播放器
```bash
python3 -m qdp.web.server
```

服务器会打印监听地址，如 `QDP web server listening on http://127.0.0.1:17890/`，持续运行直到手动停止。

可复现的本地冒烟测试序列：

```bash
curl -i http://127.0.0.1:17890/
curl -i http://127.0.0.1:17890/app/
curl -i http://127.0.0.1:17890/nope
curl -i http://127.0.0.1:17890/stream
curl -i 'http://127.0.0.1:17890/api.json/0.2/test?x=1'
python3 scripts/webplayer_smoke.py --json
python3 -m pytest -q tests/test_web_server_runtime.py tests/test_web_player_frontend_contract.py tests/test_webplayer_smoke_cli.py
```

`webplayer_smoke.py` 默认会自动启动本地网页播放器，还支持：
- `python3 scripts/webplayer_smoke.py --json` — 自动启动 + 机器可读 JSON 输出
- `python3 scripts/webplayer_smoke.py --base-url http://127.0.0.1:17890 --no-start` — 复用已有服务器实例
- `python3 scripts/webplayer_smoke.py --base-url http://127.0.0.1:17890 --no-start --json` — 复用已有实例并输出稳定 JSON

预期结果：
- `/` 重定向到 `/app/`
- `/app/` 返回 `200`
- `/nope` 返回 `404`
- `/stream` 无 `url` 参数返回 `400`
- `/api.json/0.2/test?x=1` 返回 `200` 和描述活跃代理/运行时合约的 JSON
- `webplayer_smoke.py --json` 返回可解析的 JSON，验证运行时版本一致性、核心 API 路由、流代理行为和前端 DOM 合约

### 代理配置

在 `~/.config/qobuz-dl/config.ini` 中添加 `proxies` 字段（或通过配置向导设置）：

```ini
[DEFAULT]
proxies = https://proxy1.example.com,https://proxy2.example.com
```

下载和 API 请求会自动轮询代理节点，失败自动切换，全部失败后直连兜底。

### Bundle / 网页密钥

`bundle.py` 模块用于抓取 Qobuz 网页密钥。默认上游为 `play.qobuz.com`（官方）。可通过 `QDP_BUNDLE_URL` 环境变量设置自定义镜像。

支持的运行时环境变量：
- `QDP_WEB_HOST` — 本地 HTTP 服务器绑定地址
- `QDP_WEB_PORT` — 本地 HTTP 服务器绑定端口
- `QDP_BUNDLE_URL` — 自定义 Qobuz 镜像 URL（用于抓取网页密钥）
- `QDP_APP_ID` 或 `QOBUZ_APP_ID` — 代理路由使用的 Qobuz 应用 ID
- `QDP_AUTH_TOKEN`、`QOBUZ_AUTH_TOKEN` 或 `QOBUZ_USER_AUTH_TOKEN` — 转发到已认证 Qobuz API 调用的认证 Token
- `QDP_USER_AGENT` 或 `QOBUZ_USER_AGENT` — 上游 API、资源和流请求使用的 User-Agent
- `QDP_USE_TOKEN` 或 `QOBUZ_USE_TOKEN` — 可选的 Token 模式覆盖

## 测试
从仓库根目录运行自动化测试套件：

```bash
pytest -q
```

仓库已包含 `pytest.ini`，备份文件夹不会被收集为测试。

仅限本地的构建输出和缓存（如 `build/`、`dist/`、`__pycache__/`、`.pytest_cache/`、虚拟环境目录）不应提交；它们可以在本地打包或测试运行时安全地重新生成。

如果尚未安装 pytest：

```bash
python -m pip install -r requirements-build.txt
pytest -q
```

## 打包
安装构建依赖：

```bash
python -m pip install -r requirements-build.txt
```

使用 PyInstaller 构建：

```bash
python -m PyInstaller --clean --noconfirm qdp.spec
```

推荐的便携式辅助脚本（适用于类 Unix shell，当 `python` 不可用时自动检测 `python3`）：

```bash
./build_windows.sh
```

辅助脚本功能：
- 创建隔离的 `.venv-build` 虚拟环境
- 安装运行时和构建依赖
- 运行 `python -m PyInstaller --clean --noconfirm qdp.spec`
- 验证 `dist/qdp/qdp`、`dist/qdp/qdp.exe` 或旧的扁平 `dist/qdp(.exe)` 存在
- 在声明成功之前用 `--help` 冒烟检查构建产物

平台辅助脚本：
- `build_windows.bat`
- `build_windows.ps1`
- `build_windows.sh`

## 项目文档
- 产品规格：`docs/PRD.md`
- 备份策略：`docs/backup-and-restore.md`
- 完成定义：`docs/definition-of-done.md`


## 网页应用维护

网页层现在有专门的维护说明：
- `docs/webapp-maintenance.md`

此领域主要与 Kerry 的贡献范围对齐：Web UI、浏览器交互和前端可维护性。


## 网页应用演示

- 在线演示：https://b2ab7e62.qdp-webapp-demo.pages.dev
- 部署地址：https://b2ab7e62.qdp-webapp-demo.pages.dev
- 最新 UI：v2.13.0（可刷新路由、手机搜索类型按钮、搜索历史、artist 页多端布局修复）
- 最后更新：2026-06-15
- 演示模式：**Pages 上的静态 mock 演示**（用于展示 UI/交互，不连接真实 qdp Python 运行时）

### 网页应用预览

桌面端搜索路由已持久化，刷新后仍能恢复歌手搜索结果：

![qdp webapp preview](docs/screenshots/webapp-home.jpg)

歌手详情页已补齐返回、sticky 分页信息和更紧凑的专辑网格：

![qdp webapp artist detail](docs/screenshots/webapp-album.jpg)

手机端现在有独立搜索框，聚焦后会在下方弹出 4 个搜索类型按钮：

![qdp webapp mobile search](docs/screenshots/webapp-mobile-search.jpg)

### TUI 预览

![qdp TUI search](docs/screenshots/tui-search.svg)


## 维护者

- **Lingion**：主线集成、基础设施、部署和仓库质量
- **Kerry1020**：网页应用、UI、浏览器端行为和前端维护

> 仓库说明：`lingion/qdp` 是主仓库。`Kerry1020/qdp` 是镜像，跟主仓库保持同步。Kerry1020 是具有写权限的协作者。

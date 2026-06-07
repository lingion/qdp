# QDP

本地 Qobuz 工具箱 —— 命令行下载 + 网页播放器，开箱即用。

[English](README.md) | 中文

## 功能

- **CLI/TUI 交互式下载器** — 搜索、下载专辑/单曲/歌单，支持 Hi-Res FLAC
- **本地网页播放器** — 浏览器打开即用，完整播放队列、歌单管理、音质切换
- **多账号管理** — 邮箱登录或 Token 登录，自由切换
- **代理池支持** — 配置多个代理节点自动轮询，挂了自动切，全挂直连兜底
- **完整性校验** — 下载后自动验证，支持修复和重新下载缺失曲目

## 快速开始

### 环境要求

- Python 3.9+
- pip
- 一个 Qobuz 账号（付费订阅）

### 安装

```bash
git clone https://github.com/lingion/qdp.git
cd qdp

python3 -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e . --no-build-isolation
```

### 首次配置

```bash
qdp -r
```

配置向导会引导你完成：
1. **登录方式** — 邮箱/密码（推荐）或 Token
2. **密钥选择** — 默认安卓密钥（开箱即用）、自动抓取网页密钥、或手动输入自己的 App ID / Secret
3. **下载目录** — 默认为当前目录下的 `Qobuz Downloads`
4. **音质偏好** — MP3、16-bit FLAC、24-bit Hi-Res 等

### 使用

```bash
# 启动交互式界面（推荐）
qdp

# 命令行搜索
qdp -s "周杰伦"
qdp -sa "范特西"     # 搜索专辑
qdp -st "晴天"       # 搜索单曲

# 下载指定链接
qdp "https://www.qobuz.com/album/xxxxx"

# 查看 help
qdp --help
qdp --version
```

## 网页播放器

```bash
# 方式一：在 TUI 里输入 w 回车
qdp

# 方式二：直接启动服务器
python3 -m qdp.web.server
```

启动后自动打开浏览器，地址通常是 `http://127.0.0.1:17890/`

### 功能

- 搜索并播放 Qobuz 曲库
- 播放队列管理（拖拽排序、单曲循环、随机播放）
- 音质实时切换（播放中切换，保持进度）
- 单曲/专辑下载
- 歌单管理
- 多账号切换
- 发现页（随机推荐）
- 文件浏览器（浏览已下载的音乐）

### 环境变量

| 变量 | 说明 |
|------|------|
| `QDP_WEB_HOST` | 绑定地址（默认 `127.0.0.1`） |
| `QDP_WEB_PORT` | 绑定端口（默认 `17890`） |
| `QDP_BUNDLE_URL` | 自定义 Qobuz 镜像地址（用于抓取网页密钥） |
| `QDP_APP_ID` | Qobuz App ID |
| `QDP_AUTH_TOKEN` | Qobuz 认证 Token |

## 代理配置

在配置向导或直接编辑 `~/.config/qobuz-dl/config.ini`，添加 `proxies` 字段：

```ini
[DEFAULT]
proxies = https://proxy1.example.com,https://proxy2.example.com
```

下载和 API 请求会自动轮询代理节点，失败自动切换，全挂了直连兜底。

## 依赖

核心依赖（`requirements.txt`）：
- `pathvalidate` — 文件名安全处理
- `requests` — HTTP 请求
- `mutagen` — 音频元数据读写
- `beautifulsoup4` — HTML 解析
- `rich` — 终端美化输出

构建依赖（`requirements-build.txt`）：包含 PyInstaller 等，打包时需要。

## 测试

```bash
python -m pip install -r requirements-build.txt
python -m pytest -q
```

## 打包

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm qdp.spec
```

产物在 `dist/qdp/` 目录下。

## 项目结构

```
qdp/
├── cli.py           # 命令行入口
├── ui.py            # TUI 交互界面
├── core.py          # 核心下载逻辑
├── downloader.py    # 下载管线（重试、代理、并发）
├── qopy.py          # Qobuz API 客户端
├── config.py        # 配置向导
├── accounts.py      # 多账号管理
├── integrity.py     # 完整性校验
├── metadata.py      # 音频标签写入
├── db.py            # 下载记录数据库
├── bundle.py        # 网页密钥抓取
├── sidecar.py       # 附属元数据
├── web/
│   ├── server.py    # 本地 Web 服务器
│   └── app/         # 前端（HTML/JS/CSS）
├── tests/           # 自动化测试
└── docs/            # 项目文档
```

## 维护者

- **Lingion** — 主线集成、基础设施、部署、代码质量
- **Kerry1020** — 网页播放器、前端 UI、浏览器交互

# qdp

Search, explore and download Lossless and Hi-Res music from [Qobuz](https://www.qobuz.com/).  
本仓库为 qobuz-dl 的改动/精简版，命令行可执行名为 `qdp`（模块路径仍为 `qobuz_dl`）。

[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=VZWSWVGZGJRMU&source=url)

## Features

- 通过 URL / 文本文件 / Last.fm / 艺人 / 歌单 / 厂牌批量下载专辑 / 单曲 / 歌单 / 厂牌内容。
- 支持 MP3 / FLAC / Hi‑Res（多种画质代码）；可选画质回退策略。
- 交互式搜索与选择、分页、结果多选并发下载。
- 嵌入封面、生成 M3U、智能艺人筛选（去重/过滤）。
- 本地去重数据库（可跳过或清空）。
- 支持代理池与强制直连模式。
- 支持 albums-only、no-m3u、no-fallback、folder/track 格式模板等高级选项。

---

## Getting started

> 你需要一个有效的 Qobuz 订阅账号（部分 Hi‑Res 内容可能需要更高会员等级）。

本节仅说明如何从本仓库源码安装并运行 qdp（不包含其它平台/发布版安装说明）。

### 源码安装（推荐在虚拟环境中）

1. 克隆仓库或下载源码：
```bash
git clone https://github.com/lingion/qdp.git
cd qdp
```

2. 建议使用虚拟环境：
```bash
python3 -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

3. 升级 pip 并安装依赖：
```bash
pip install --upgrade pip
pip install -r requirements.txt
```
- Windows 用户：如遇 curses 相关错误，先安装 `windows-curses`：
```bash
pip install windows-curses
```

4. 从源码安装（两种方式任意其一）：
- 可编辑安装（推荐开发 / 调试）：
```bash
pip install -e .
```
- 常规安装：
```bash
python3 setup.py install
# 或
pip install .
```

安装完成后，系统应会生成 `qdp` 可执行命令（Windows 下为 `qdp.exe`）。

可选：构建 wheel 并安装
```bash
python3 setup.py bdist_wheel
pip install dist/your_generated_wheel.whl
```

---

## 搜索功能（交互式搜索与使用说明）

qdp 提供交互式搜索并支持直接从搜索结果选择要下载的项。搜索相关的命令行参数如下（详见代码 qobuz_dl/commands.py）：

- -s, --search QUERY
  - 默认的搜索入口，按专辑（album）搜索。
- -sa, --search-album QUERY
  - 明确按专辑搜索（等同 -s）。
- -st, --search-track QUERY
  - 按单曲（track）搜索。
- -si, --search-artist QUERY
  - 按艺人（artist）搜索（通常用于批量下载某艺人的专辑）。

重要参数：
- -l, --limit INT
  - 每页显示的搜索结果数（默认 10）。该值决定一次检索返回多少条结果并在交互界面中显示多少项，配合分页使用。
- -q, --quality INT
  - 指定目标画质（5/6/7/27 等），影响后续下载请求的质量偏好。

交互式搜索行为（在命令运行后）：
1. 发起搜索后，界面会以表格展示当前页的结果（序号、标题、艺术家、画质、年份等）。
2. 可输入下列交互命令：
   - 输入以逗号分隔的序号（例如 `1,3,5`）选择对应条目并开始下载这些条目。
   - `n`：下一页（offset + limit）。
   - `p`：上一页（offset - limit）。
   - `0`：退出搜索并返回主流程。
3. 选择后，程序会把选中的条目转换为对应的 Qobuz 链接并交由下载流程处理（会按你的质量设置和其他选项执行）。
4. 搜索完成后可继续新关键词搜索（程序会提示是否继续并允许直接输入新关键词或回车退出）。

交互示例：
- 搜索专辑并显示 5 条结果：
```bash
qdp -s "fka twigs magdalene" -l 5
```
在交互界面输入 `1,2` 将同时下载第 1 和第 2 条结果；输入 `n` 翻到下一页。

- 搜索单曲并选择下载若干曲目：
```bash
qdp -st "eric dolphy remastered" -l 10 -q 5
```

- 搜索艺人并使用智能编目（需在 config 或命令行启用 smart_discography）：
```bash
qdp -si "joy division" -l 20
```
当下载艺人条目时，可开启 `--smart-discography`（或在配置中启用）以过滤重复或杂乱的专辑，减少垃圾条目。

Lucky 模式（若仓内实现）
- 如果你实现并使用了 `lucky` 子命令，它通常会使用给定的搜索关键词直接下载第 N 个结果（或前 N 个结果）。示例（若可用）：
```bash
qdp lucky "playboi carti die lit"        # 下载第一个匹配的专辑或曲目（视 type）
qdp lucky "joy division" -n 5 --type artist
```
（请以 `qdp lucky --help` 输出为准）

注意事项
- 搜索默认类型是“专辑”，除非使用 `--search-track` 或 `--search-artist` 明确指定类型。
- `--limit` 决定每页结果数量；可以配合 `n/p` 分页浏览更多结果。
- 搜索结果中如果某条目标注为不可用（非 streamable），交互界面会标出，下载时可能失败或抛出错误。
- 使用搜索下载艺人全集时请注意 `--albums-only`、`--smart-discography` 等选项对结果的影响。

---

## 快速使用示例（命令行）

- 运行并输入凭据（首次运行将创建配置）：
```bash
qdp
# Windows:
qdp.exe
```

- 重置配置：
```bash
qdp -r
```

- 下载专辑（示例：24/96，使用 -q 指定画质代码）：
```bash
qdp dl https://play.qobuz.com/album/qxjbxh1dc3xyb -q 7
```

- 下载多个 URL 到自定义目录：
```bash
qdp dl https://play.qobuz.com/artist/2038380 https://play.qobuz.com/album/ip8qjy1m6dakc -o "Some pop from 2020"
```

- 从文本文件批量下载（每行一个 URL）：
```bash
qdp dl urls.txt
```

- 下载歌单并嵌入封面：
```bash
qdp dl https://play.qobuz.com/label/7526 --embed-art
```

- 交互式搜索并限制结果数：
```bash
qdp -s "fka twigs magdalene" -l 10
```

- 跳过数据库去重检查并强制下载：
```bash
qdp dl <URL> --no-db
```

运行任一子命令的帮助：
```bash
qdp dl --help
qdp fun --help
qdp lucky --help
```

---

## Usage（整体命令摘要）
（命令行参数以仓库内实现为准）
```
usage: qdp [-h] [-r] {fun,dl,lucky} ...

The ultimate Qobuz music downloader.

optional arguments:
  -h, --help      show this help message and exit
  -r, --reset     create/reset config file
  -p, --purge     purge/delete downloaded-IDs database

commands:
  run qdp <command> --help for more info
  (e.g. qdp fun --help)

  {fun,dl,lucky}
    fun           interactive mode
    dl            input mode
    lucky         lucky mode
```

---

## Module usage

示例：在 Python 脚本中以模块方式使用核心类（module path 保持 qobuz_dl）：
```python
import logging
from qobuz_dl.core import QobuzDL

logging.basicConfig(level=logging.INFO)

email = "your@email.com"
password = "your_password"

qobuz = QobuzDL()
qobuz.get_tokens()  # 获取 app_id 与 secrets（依实现而定）
qobuz.initialize_client(email, password, qobuz.app_id, qobuz.secrets)
qobuz.handle_url("https://play.qobuz.com/album/va4j3hdlwaubc")
```

---

## 配置说明（代码内默认位置）
- 配置目录（由代码决定）：
  - Windows: %APPDATA%/qobuz-dl
  - Unix: ~/.config/qobuz-dl
- 配置文件: config.ini（位于上述目录）
- 下载去重数据库: qobuz_dl.db（位于上述目录）

首次运行或使用 `qdp -r` 可进入交互式配置向导，设置登录方式（邮箱/密码 或 token）、默认画质、代理池等。

---

## 关于 Qo‑DL
本项目受 Qo‑DL‑Reborn 启发，并使用了其某些模块（如 qopy、spoofer）。见代码中相关注释与引用。

---

## Disclaimer
- 本工具仅供学习与研究使用。请在使用前遵守 Qobuz 的服务条款以及当地法律法规。
- 本项目与 Qobuz 官方无关联。作者不对不当使用造成的后果负责。

---

## License
请参阅仓库中的 LICENSE 文件以获取许可信息。
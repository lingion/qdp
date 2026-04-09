# qdp Web Player

## 访问地址
- 默认本地地址：`http://127.0.0.1:17890/app/`
- 启动：`python -m qdp.web.server`

## 版本号查看
- Python 单一来源：`qdp/web/__init__.py` 里的 `__version__`
- 运行中版本：`GET /__version` 或 `GET /api/meta`
- 前端显示版本：页面右上角版本号，启动后由 `/api/meta` 拉取并显示

## 一键自测
```bash
# 自动启动本地服务并验证
python scripts/webplayer_smoke.py

# 复用已运行服务
python scripts/webplayer_smoke.py --base-url http://127.0.0.1:17890 --no-start

# JSON 输出（适合脚本/CI）
python scripts/webplayer_smoke.py --json
```

脚本会验证：
- `/app/`
- `/__version`
- `/api/meta`
- `/api/discover-random-albums`
- `/api/me`
- `/api/search?type=tracks&q=daft%20punk`
- `/api/track-url -> /stream` Range 206
- `/app/app.css`
- `/app/app.js`

## 本轮新增
- 首页在搜索框为空时，会展示“随机专辑”区块，数据来自本地后端 `/api/discover-random-albums`
- 播放器新增音量滑杆、静音按钮，并使用 localStorage 持久化音量/静音状态
- Queue 来源信息进一步标准化，当前来源会以轻量 badge/pill 展示
- 状态脚本补充了更贴近真实交互的 contract：连点 next/prev、ended 自动 next、queue reorder 后 current 保持、volume mute 行为

## 简短架构
- 本地 UI：`qdp/web/app/` 下的静态页面与脚本
- 本地 token：服务端从本地配置/环境读取，不在前端暴露 secret
- 本地 `/stream`：前端拿到的播放链接统一回到本地 `/stream`，再由服务端代理上游音频流

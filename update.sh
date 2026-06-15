#!/usr/bin/env bash
# QDP 一键更新（macOS / Linux / Termux 通用）
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/lingion/qdp/main/update.sh | bash
# 或本地：
#   bash update.sh
set -e

# ─── 颜色 ───
R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; N='\033[0m'

log()   { printf "${B}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${Y}!${N} %s\n" "$*"; }
err()   { printf "${R}✗${N} %s\n" "$*" >&2; }
hr()    { printf "${B}─────────────────────────────────────────${N}\n"; }

# ─── 平台检测 ───
detect_platform() {
  case "$(uname -s)" in
    Darwin) PLATFORM="macos" ;;
    Linux)
      if [ -d /data/data/com.termux ]; then
        PLATFORM="termux"
      else
        PLATFORM="linux"
      fi
      ;;
    *) err "不支持的平台: $(uname -s)"; exit 1 ;;
  esac
  log "平台: $PLATFORM"
}

# ─── 定位 qdp 目录 ───
find_qdp_dir() {
  if [ -n "$QDP_DIR" ] && [ -d "$QDP_DIR" ]; then
    return
  fi
  for cand in "$HOME/qdp" "$HOME/.qdp" "$(pwd)/qdp" "$(pwd)"; do
    if [ -d "$cand" ] && [ -f "$cand/setup.py" ] && [ -d "$cand/qdp" ]; then
      QDP_DIR="$cand"
      return
    fi
  done
  err "找不到 qdp 目录。请先跑 install.sh 装一次："
  err "  curl -fsSL https://raw.githubusercontent.com/lingion/qdp/main/install.sh | bash"
  exit 1
}

# ─── 备份 config.ini ───
backup_config() {
  local cfg=""
  if [ "$PLATFORM" = "termux" ]; then
    cfg="$HOME/.config/qobuz-dl/config.ini"
  elif [ -f "$HOME/.config/qobuz-dl/config.ini" ]; then
    cfg="$HOME/.config/qobuz-dl/config.ini"
  elif [ -f "$HOME/Library/Application Support/qobuz-dl/config.ini" ]; then
    cfg="$HOME/Library/Application Support/qobuz-dl/config.ini"
  fi
  if [ -n "$cfg" ] && [ -f "$cfg" ]; then
    local bak="${cfg}.bak.$(date +%s)"
    cp "$cfg" "$bak"
    ok "配置已备份: $bak"
  fi
}

# ─── 拉最新代码（绕过 git pull 超时） ───
sync_code() {
  log "拉最新 main commit…"
  cd "$QDP_DIR"
  
  # 1. 先试 git fetch（如果能跑通就用）
  if timeout 15 git fetch origin main 2>/dev/null; then
    log "git fetch 成功，merge…"
    if ! git merge origin/main --ff-only 2>&1 | tail -5; then
      warn "git merge 失败（可能有本地未提交修改），改用 gh api 拉文件"
    else
      ok "git 同步完成"
      return
    fi
  else
    warn "git fetch 超时，改用 gh api 拉文件"
  fi
  
  # 2. 用 gh api 拉 4 个核心前端文件（绕过 HTTPS 直连超时）
  if command -v gh >/dev/null 2>&1; then
    local files="qdp/web/app/api.js qdp/web/app/app.js qdp/web/app/core.js qdp/web/app/index.html qdp/web/app/app.css"
    for f in $files; do
      local bn=$(basename "$f")
      log "  拉 $f"
      if gh api "repos/lingion/qdp/contents/$f?ref=main" -q '.content' 2>/dev/null | base64 -d > "$f.tmp" 2>/dev/null; then
        if [ -s "$f.tmp" ]; then
          mv "$f.tmp" "$f"
        fi
      fi
    done
    ok "前端文件已同步到 main"
    return
  fi
  
  # 3. 兜底：直接 git pull
  log "兜底用 git pull…"
  git pull origin main || err "git pull 失败，请手动: cd $QDP_DIR && git pull"
}

# ─── 重装包 ───
reinstall() {
  log "激活 venv…"
  cd "$QDP_DIR"
  if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  else
    err "找不到 venv: $QDP_DIR/.venv"
    err "请先跑 install.sh 安装"
    exit 1
  fi
  
  log "装 setuptools/wheel（防 venv 缺这俩包）"
  pip install --quiet --upgrade setuptools wheel 2>&1 | tail -3 || true
  
  log "重新 pip install -e .（开发模式，立即生效）"
  pip install -e . --quiet 2>&1 | tail -3
  ok "包已重装"
}

# ─── 显示版本号 + 强刷提示 ───
show_info() {
  cd "$QDP_DIR"
  local ver
  ver=$(python3 -c "import qdp; print(getattr(qdp, '__version__', '?'))" 2>/dev/null || echo "?")
  
  hr
  ok "更新完成！"
  log "qdp 版本: $ver"
  log "代码位置: $QDP_DIR"
  hr
  
  # 浏览器强刷提示
  printf "\n"
  printf "${Y}⚠️  重要：必须强刷新浏览器才能看到新前端${N}\n"
  printf "\n"
  printf "  ${B}iPhone Safari${N}:\n"
  printf "    • 设置 → Safari → 高级 → 网站数据 → 删除 127.0.0.1\n"
  printf "    • 或: 长按刷新按钮 → 重新载入无缓存内容\n"
  printf "    • 或: 开无痕模式（最简单）\n"
  printf "\n"
  printf "  ${B}Android Chrome${N}:\n"
  printf "    • 右上角 ⋮ → 设置 → 隐私和安全 → 清除浏览数据\n"
  printf "    • 或: 右上角 ⋮ → 新建无痕式标签页（最简单）\n"
  printf "\n"
  printf "  ${B}桌面浏览器${N}:\n"
  printf "    • ${Y}Cmd/Ctrl + Shift + R${N} 强刷\n"
  printf "    • 或: DevTools 打开 → 右键刷新 → 清缓存硬性重新加载\n"
  printf "\n"
  hr
}

# ─── 主流程 ───
main() {
  hr
  printf "${B}  QDP 一键更新${N}\n"
  hr
  printf "\n"
  
  detect_platform
  find_qdp_dir
  ok "qdp 目录: $QDP_DIR"
  
  backup_config
  sync_code
  reinstall
  show_info
}

main "$@"

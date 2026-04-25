from __future__ import annotations

import configparser
import re
import webbrowser
from typing import Dict, List

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from qdp.accounts import create_account_record, delete_account, format_account_display, get_active_account, list_accounts, rename_account, save_current_as_account, set_account_remark, switch_account, update_account_meta
from qdp.config import CONFIG_FILE, DEFAULT_SETTINGS, QOBUZ_DB, initial_checks, load_config, load_config_defaults, run_config_wizard, save_config
from qdp.core import QobuzDL
from qdp.db import iter_download_entries
from qdp.exceptions import AuthenticationError, InvalidAppIdError, InvalidAppSecretError, AppSecretValidationProxyError
from qdp.integrity import discover_library_albums
from qdp.ui_compound import CompoundAction, build_plan, choose_action, confirm_execution, run_plan
from qdp.ui_models import SelectionSet, UIItem, UIItemKind

# 莫兰迪柔和配色
C_BORDER = "#8e9aaf"   # 雾霾蓝灰
C_TITLE = "#b39bc8"    # 灰紫
C_DIM = "#9ca3af"      # 烟灰
C_OK = "#8fb996"       # 鼠尾草绿
C_WARN = "#d4b483"     # 杏米色
C_ACCENT = "#a3b18a"   # 橄榄灰绿


def _to_int(val, fallback):
    try:
        return int(val)
    except Exception:
        return fallback


def _to_bool_str(value: str) -> bool:
    return str(value or "").strip().lower() == "true"


def build_qobuz_from_defaults(defaults: Dict[str, str]) -> QobuzDL:
    cfg_workers = _to_int(defaults.get("workers", "4"), 4)
    cfg_prefetch = (defaults.get("prefetch_workers") or "").strip()
    cfg_prefetch_workers = _to_int(cfg_prefetch, None) if cfg_prefetch else None
    cfg_max_retries = _to_int(defaults.get("max_retries", "4"), 4)
    cfg_timeout = _to_int(defaults.get("timeout", "30"), 30)
    cfg_url_rate = _to_int(defaults.get("url_rate", "8"), 8)
    cfg_force_proxy = _to_bool_str(defaults.get("force_proxy", "false"))
    return QobuzDL(
        defaults.get("default_folder", DEFAULT_SETTINGS["default_folder"]),
        _to_int(defaults.get("default_quality", DEFAULT_SETTINGS["default_quality"]), 27),
        _to_bool_str(defaults.get("embed_art", "false")),
        ignore_singles_eps=_to_bool_str(defaults.get("albums_only", "false")),
        no_m3u_for_playlists=_to_bool_str(defaults.get("no_m3u", "false")),
        quality_fallback=not _to_bool_str(defaults.get("no_fallback", "false")),
        cover_og_quality=_to_bool_str(defaults.get("og_cover", "false")),
        no_cover=_to_bool_str(defaults.get("no_cover", "false")),
        downloads_db=QOBUZ_DB,
        folder_format=defaults.get("folder_format", DEFAULT_SETTINGS["folder_format"]),
        track_format=defaults.get("track_format", DEFAULT_SETTINGS["track_format"]),
        smart_discography=_to_bool_str(defaults.get("smart_discography", "false")),
        no_booklet=_to_bool_str(defaults.get("no_booklet", "false")),
        verify_existing=_to_bool_str(defaults.get("verify_existing", "false")),
        check_only=False,
        workers=cfg_workers,
        prefetch_workers=cfg_prefetch_workers,
        max_retries=cfg_max_retries,
        timeout=cfg_timeout,
        url_rate=cfg_url_rate,
        force_proxy=cfg_force_proxy,
    )


def initialize_qobuz_client(qobuz: QobuzDL, defaults: Dict[str, str]):
    secrets = [s for s in (defaults.get("secrets") or "").split(",") if s]
    qobuz.initialize_client(
        defaults.get("email", ""),
        defaults.get("password", ""),
        defaults.get("app_id", ""),
        secrets,
        defaults.get("use_token", "false"),
        defaults.get("user_id", ""),
        defaults.get("user_auth_token", ""),
    )
    try:
        active = get_active_account(CONFIG_FILE) or defaults.get('email') or defaults.get('user_id') or 'default'
        meta = getattr(qobuz.client, 'account_meta', {}) or {}
        if meta:
            non_empty_meta = {k: str(v) for k, v in meta.items() if str(v or '').strip()}
            defaults.update(non_empty_meta)
            update_account_meta(active, meta, CONFIG_FILE, overwrite_empty=False)
    except Exception:
        pass


def _header(console: Console, breadcrumb: str, subtitle: str = ""):
    # show web player version so user can tell if a rebuild/restart is needed
    try:
        from qdp.web.server import WEB_PLAYER_VERSION
        v = WEB_PLAYER_VERSION
    except Exception:
        v = "?"
    title = f"[bold {C_TITLE}]qdp Dashboard[/] [dim]web:{v}[/]"
    meta = f"[{C_DIM}]{breadcrumb}[/]"
    body = title + (f"\n{subtitle}" if subtitle else "") + f"\n{meta}"
    console.print(Panel(Align.left(body), border_style=C_BORDER))


def _recent_summary_table() -> Table:
    entries = list(iter_download_entries(QOBUZ_DB))
    table = Table(title="最近操作摘要（DB）", border_style=C_BORDER)
    table.add_column("时间", style=C_DIM, no_wrap=True)
    table.add_column("ID", style=C_DIM, no_wrap=True)
    table.add_column("状态")
    table.add_column("路径")
    for row in entries[:10]:
        ts = (row.get("last_checked") or "")[:19].replace("T", " ")
        table.add_row(ts or "-", str(row.get("id")), str(row.get("integrity_status") or "-"), str(row.get("local_path") or "-"))
    return table


def _pause(console: Console):
    console.input(f"[{C_DIM}]回车继续...[/]")


def _mask_email(email: str) -> str:
    email = (email or '').strip()
    if not email or '@' not in email:
        return email
    local, domain = email.split('@', 1)
    left = local[:3]
    right = local[-2:] if len(local) > 2 else ''
    return f"{left}..{right}@{domain}"


def _account_status_from_exception(exc: Exception) -> tuple[str, str]:
    msg = str(exc)
    status = '异常'
    if 'Token 无效' in msg or '过期' in msg:
        status = 'token 无效'
    elif 'App Secret' in msg or 'App ID' in msg or '签名' in msg:
        status = 'secret 失效'
    elif '不可串流' in msg or '版权' in msg:
        status = '不可用'
    return status, msg[:200]



def _refresh_account_profile(account_name: str, console: Console, test_availability: bool = False, progress: str = ''):
    prefix = f'{progress}: ' if progress else ''
    mode_text = '测试账号' if test_availability else '刷新资料'
    console.print(f'[{C_DIM}]{prefix}正在{mode_text}:[/] {account_name}')
    switch_account(account_name, CONFIG_FILE)
    latest = load_config_defaults(CONFIG_FILE)
    q = build_qobuz_from_defaults(latest)
    initialize_qobuz_client(q, latest)
    meta = {'status': '可用', 'status_detail': ''} if test_availability else {}
    update_account_meta(account_name, meta, CONFIG_FILE, overwrite_empty=False)
    return load_config_defaults(CONFIG_FILE)



def _ui_account_center(console: Console, defaults: Dict[str, str]) -> bool:
    state_changed = False
    while True:
        console.clear()
        active = get_active_account(CONFIG_FILE)
        _header(console, breadcrumb="Dashboard > Accounts", subtitle=f"当前账号: {active or '未命名'}")
        accounts = list_accounts(CONFIG_FILE)
        table = Table(title="账号中心", border_style=C_BORDER)
        table.add_column("编号", justify="right", style=C_DIM)
        table.add_column("账号")
        if accounts:
            for idx, (name, data) in enumerate(accounts, start=1):
                table.add_row(str(idx), format_account_display(idx, name, data, active))
        else:
            table.add_row('-', '还没有历史账号记录')
        console.print(table)
        console.print(f"[{C_DIM}]输入序号一键切换 | n 新增账号 | s 保存当前账号 | r 重命名 | m 备注 | d 删除 | t 测当前 | T 测全部 | u 刷新当前资料 | U 刷新全部资料 | b 返回[/]")
        raw = (console.input('选择: ') or '').strip()
        cmd = raw.lower()
        if cmd in {'b', 'q', '0'}:
            return state_changed
        if cmd == 'n':
            acc_type = (console.input("新增类型 [1] 邮箱账号 [2] Token账号: ") or '').strip()
            payload = {}
            if acc_type == '2':
                payload['use_token'] = 'true'
                payload['email'] = ''
                payload['password'] = ''
                payload['user_id'] = (console.input('User ID: ') or '').strip()
                payload['user_auth_token'] = (console.input('Token: ') or '').strip()
                payload['app_id'] = defaults.get('app_id', '')
                payload['secrets'] = defaults.get('secrets', '')
                payload['account_type'] = 'token'
            else:
                payload['use_token'] = 'false'
                payload['email'] = (console.input('邮箱: ') or '').strip()
                payload['password'] = (console.input('密码: ') or '').strip()
                payload['user_id'] = ''
                payload['user_auth_token'] = ''
                payload['app_id'] = defaults.get('app_id', '')
                payload['secrets'] = defaults.get('secrets', '')
                payload['account_type'] = 'account'
            payload['region'] = (console.input('地区/区域(例如 US/JP，可空): ') or '').strip() or '--'
            payload['expiry_date'] = (console.input('到期日期(YYYY-MM-DD，可空): ') or '').strip()
            payload['remark'] = (console.input('备注(可空): ') or '').strip()
            suggested = payload.get('email') or payload.get('user_id') or 'account'
            name = (console.input(f'账号名称 [{suggested}]: ') or '').strip() or suggested
            create_account_record(name, payload, CONFIG_FILE)
            console.print('[green]已新增账号。[/]')
            state_changed = True
            _pause(console)
            continue
        if cmd == 's':
            suggested = defaults.get('email') or defaults.get('user_id') or defaults.get('active_account') or 'default'
            name = (console.input(f'保存账号名称 [{suggested}]: ') or '').strip() or suggested
            meta = {
                'region': defaults.get('region', '--'),
                'expiry_date': defaults.get('expiry_date', ''),
                'label': defaults.get('label', ''),
                'account_type': 'token' if defaults.get('use_token') == 'true' else 'account',
                'email_masked': _mask_email(defaults.get('email', '')),
                'user_id_masked': str(defaults.get('user_id', ''))[:4],
            }
            save_current_as_account(name, defaults=defaults, config_file=CONFIG_FILE, meta=meta)
            console.print('[green]已保存当前账号。[/]')
            state_changed = True
            _pause(console)
            continue
        if raw == 't':
            try:
                defaults.update(_refresh_account_profile(active or 'default', console, test_availability=True))
                console.print('[green]当前账号测试成功：可用[/]')
                state_changed = True
            except Exception as exc:
                status, detail = _account_status_from_exception(exc)
                update_account_meta(active or 'default', {'status': status, 'status_detail': detail}, CONFIG_FILE)
                console.print(f'[red]当前账号测试失败：[/]{exc}')
                state_changed = True
            _pause(console)
            continue
        if cmd == 'u' and raw == 'u':
            try:
                defaults.update(_refresh_account_profile(active or 'default', console, test_availability=False))
                console.print('[green]当前账号资料已刷新。[/]')
                state_changed = True
            except Exception as exc:
                console.print(f'[red]当前账号资料刷新失败：[/]{exc}')
            _pause(console)
            continue
        if raw in {'T', 'U'}:
            total = len(accounts)
            original_active = active
            mode_test = raw == 'T'
            for idx, (name, data) in enumerate(accounts, start=1):
                progress = f'{idx}/{total}'
                try:
                    latest = _refresh_account_profile(name, console, test_availability=mode_test, progress=progress)
                    if name == original_active:
                        defaults.update(latest)
                    state_changed = True
                except Exception as exc:
                    if mode_test:
                        status, detail = _account_status_from_exception(exc)
                        update_account_meta(name, {'status': status, 'status_detail': detail}, CONFIG_FILE)
                    console.print(f'[red]{progress}:[/]', str(name), '失败：', str(exc))
                    state_changed = True
            if original_active:
                try:
                    switch_account(original_active, CONFIG_FILE)
                    defaults.update(load_config_defaults(CONFIG_FILE))
                except Exception:
                    pass
            console.print('[green]全部账号测试完成。[/]' if mode_test else '[green]全部账号资料刷新完成。[/]')
            _pause(console)
            continue
        if cmd == 'r':
            target = (console.input('输入要重命名的账号序号: ') or '').strip()
            if target.isdigit() and 1 <= int(target) <= len(accounts):
                old_name = accounts[int(target)-1][0]
                new_name = (console.input(f'新名称 [{old_name}]: ') or '').strip() or old_name
                rename_account(old_name, new_name, CONFIG_FILE)
                console.print(f'[green]已重命名为[/] {new_name}')
                state_changed = True
                _pause(console)
            continue
        if cmd == 'm':
            target = (console.input('输入要备注的账号序号: ') or '').strip()
            if target.isdigit() and 1 <= int(target) <= len(accounts):
                name = accounts[int(target)-1][0]
                remark = (console.input('备注内容: ') or '').strip()
                set_account_remark(name, remark, CONFIG_FILE)
                console.print('[green]备注已更新。[/]')
                state_changed = True
                _pause(console)
            continue
        if cmd == 'd':
            target = (console.input('输入要删除的账号序号: ') or '').strip()
            if target.isdigit() and 1 <= int(target) <= len(accounts):
                name = accounts[int(target)-1][0]
                delete_account(name, CONFIG_FILE)
                console.print(f'[yellow]已删除账号[/] {name}')
                state_changed = True
                _pause(console)
            continue
        if raw.isdigit() and 1 <= int(raw) <= len(accounts):
            name = accounts[int(raw)-1][0]
            switch_account(name, CONFIG_FILE)
            defaults.update(load_config_defaults(CONFIG_FILE))
            console.print(f'[green]已切换到账号:[/] {name}')
            state_changed = True
            _pause(console)
            continue


def _menu(console: Console, breadcrumb: str, qobuz: QobuzDL, defaults: Dict[str, str]):
    while True:
        console.clear()
        _header(console, breadcrumb=breadcrumb, subtitle=f"目录: {defaults.get('default_folder')}")
        table = Table(title="主面板", border_style=C_BORDER)
        table.add_column("编号", justify="right", style=C_DIM)
        table.add_column("功能")
        table.add_row("1", "搜索 (album/track/artist)")
        table.add_row("2", "粘贴 URL 批量")
        table.add_row("3", "本地库工具 (scan/doctor/rename)")
        table.add_row("4", "设置 (编辑关键默认值)")
        table.add_row("5", "账号中心 (快速切换多个账号)")
        table.add_row("6", "最近操作 / 结果摘要")
        table.add_row("w", "Web Player (本地 play.qobuz.com)")
        table.add_row("a", "Apple Player (Apple 风格 UI)")
        table.add_row("q", "退出")
        console.print(table)
        console.print(f"[{C_DIM}]快捷键: 1-6 / w(web) / a(apple) / q[/]")
        choice = (console.input("选择: ") or "").strip().lower()
        if choice in {"q", "0"}:
            return
        if choice == "1":
            _ui_search(console, qobuz, defaults)
        elif choice == "2":
            _ui_url_batch(console, qobuz)
        elif choice == "3":
            _ui_library_tools(console, qobuz)
        elif choice == "4":
            changed = _ui_settings_editor(console, defaults)
            if changed:
                defaults.update(load_config_defaults(CONFIG_FILE))
                qobuz = build_qobuz_from_defaults(defaults)
                initialize_qobuz_client(qobuz, defaults)
        elif choice == "5":
            changed = _ui_account_center(console, defaults)
            if changed:
                defaults.update(load_config_defaults(CONFIG_FILE))
                qobuz = build_qobuz_from_defaults(defaults)
                initialize_qobuz_client(qobuz, defaults)
        elif choice == "6":
            console.clear()
            _header(console, breadcrumb=f"{breadcrumb} > Recent")
            console.print(_recent_summary_table())
            _pause(console)
        elif choice in {"w", "web"}:
            try:
                from qdp.web.server import start_web_player
                url = start_web_player()
                console.print(f"[green]Web Player 已启动：[/]{url}")
                console.print(f"[{C_DIM}]已在浏览器打开（如果没弹出来就手动复制上面的链接）。[/]")
                webbrowser.open(url)
            except Exception as exc:
                console.print(f"[red]启动 Web Player 失败：[/]{exc}")
            _pause(console)
        elif choice in {"a", "apple"}:
            try:
                from qdp.web.server import start_web_player
                url = start_web_player()
                apple_url = url.rstrip("/") + "/apple/"
                console.print(f"[green]Apple Player 已启动：[/]{apple_url}")
                console.print(f"[{C_DIM}]已在浏览器打开（如果没弹出来就手动复制上面的链接）。[/]")
                webbrowser.open(apple_url)
            except Exception as exc:
                console.print(f"[red]启动 Apple Player 失败：[/]{exc}")
            _pause(console)


def _ui_search(console: Console, qobuz: QobuzDL, defaults: Dict[str, str]):
    console.clear()
    _header(console, breadcrumb="Dashboard > Search")
    console.print("[bold]搜索类型[/]  [1] album  [2] track  [3] artist  [b] 返回")
    choice = (console.input("选择: ") or "").strip().lower()
    if choice in {"b", "q", "0"}:
        return
    mapping = {"1": "album", "2": "track", "3": "artist"}
    search_type = mapping.get(choice, "album")
    query = (console.input("关键词: ") or "").strip()
    if not query:
        return
    limit = _to_int(defaults.get("default_limit", "20"), 20)
    qobuz.run_search(query, search_type, limit)
    _pause(console)


def _extract_urls(text: str) -> List[str]:
    qobuz_pattern = r"(https?://(?:open|play|www)\.qobuz\.com/[^\s\"']+)"
    return list(dict.fromkeys(re.findall(qobuz_pattern, text or "")))


def _ui_url_batch(console: Console, qobuz: QobuzDL):
    console.clear()
    _header(console, breadcrumb="Dashboard > URL Batch")
    console.print(f"[{C_DIM}]粘贴多行 URL / 文本，空行结束；b 返回[/]")
    lines = []
    while True:
        line = console.input("").rstrip("\n")
        if line.strip().lower() in {"b", "back"}:
            return
        if not line.strip():
            break
        lines.append(line)
    urls = _extract_urls("\n".join(lines))
    if not urls:
        console.print("[yellow]未识别到任何 qobuz 链接。[/]")
        _pause(console)
        return
    items = [UIItem(kind=UIItemKind.URL, label=url, payload={"url": url}) for url in urls]
    sel = SelectionSet()
    sel.select_all(len(items))
    while True:
        console.clear()
        _header(console, breadcrumb="Dashboard > URL Batch")
        table = Table(title=f"URL 列表（已选 {len(sel)} / {len(items)}）", border_style=C_BORDER)
        table.add_column("#", justify="right", style=C_DIM)
        table.add_column("选", justify="center")
        table.add_column("URL")
        selected_set = set(sel.selected_indices(len(items)))
        for idx, item in enumerate(items, start=1):
            mark = "✓" if (idx - 1) in selected_set else ""
            table.add_row(str(idx), f"[{C_OK}]{mark}[/{C_OK}]" if mark else "", item.label)
        console.print(table)
        console.print(f"[{C_DIM}]a 全选 | c 清空 | x 序号切换 | g 操作 | b 返回 | q 退出[/]")
        raw = (console.input("输入: ") or "").strip().lower()
        if raw in {"b", "back", "q", "0"}:
            return
        if raw == "a":
            sel.select_all(len(items)); continue
        if raw == "c":
            sel.clear(); continue
        if raw.startswith("x"):
            rest = raw[1:].strip() or (console.input("切换序号(逗号/空格分隔): ") or "").strip()
            from qdp.ui_compound import parse_toggle_indices
            for i in parse_toggle_indices(rest):
                sel.toggle(i, count=len(items))
            continue
        if raw == "g":
            selected = sel.selected_items(items)
            action = choose_action(console, console.input, selected, allow_rename=False)
            if not action:
                continue
            options: Dict[str, object] = {}
            if action == CompoundAction.EXPORT_REPORT:
                options['filename'] = (console.input('导出文件名(默认 qdp-report.json): ') or '').strip() or 'qdp-report.json'
            plan = build_plan(action, selected, options=options)
            if not confirm_execution(console, plan, console.input):
                continue
            run_plan(console, qobuz, plan)
            _pause(console)


def _ui_library_tools(console: Console, qobuz: QobuzDL):
    while True:
        console.clear()
        _header(console, breadcrumb="Dashboard > Library")
        table = Table(title="本地库工具", border_style=C_BORDER)
        table.add_column("编号", justify="right", style=C_DIM)
        table.add_column("功能")
        table.add_row("1", "scan-library（扫描并回填 DB）")
        table.add_row("2", "doctor（检查配置/DB/代理/目录）")
        table.add_row("3", "rename-library dry-run（预览）")
        table.add_row("4", "rename-library apply（执行）")
        table.add_row("5", "扫描结果多选（仅 rename/export）")
        table.add_row("b", "返回")
        console.print(table)
        choice = (console.input("选择: ") or "").strip().lower()
        if choice in {"b", "q", "0"}:
            return
        if choice == "1":
            qobuz.scan_library(); _pause(console)
        elif choice == "2":
            defaults = load_config_defaults(CONFIG_FILE); qobuz.doctor(defaults); _pause(console)
        elif choice == "3":
            qobuz.rename_library(dry_run=True); _pause(console)
        elif choice == "4":
            console.print("[bold yellow]即将执行重命名，会实际改动文件。确认? y/N[/]")
            if (console.input("确认: ") or "").strip().lower() in {"y", "yes"}:
                qobuz.rename_library(dry_run=False)
            _pause(console)
        elif choice == "5":
            _ui_library_scan_results(console, qobuz)


def _ui_library_scan_results(console: Console, qobuz: QobuzDL):
    candidates = discover_library_albums(qobuz.directory)
    if not candidates:
        console.print("[yellow]未发现任何本地专辑候选。[/]"); _pause(console); return
    items: List[UIItem] = []
    for cand in candidates:
        label = f"{cand.guessed_artist} - {cand.guessed_album} ({cand.guessed_year}) | {cand.integrity_status} | {cand.album_dir}"
        items.append(UIItem(kind=UIItemKind.LIBRARY_ALBUM, label=label, payload={"album_key": cand.album_key, "album_dir": cand.album_dir}))
    sel = SelectionSet()
    while True:
        console.clear(); _header(console, breadcrumb="Dashboard > Library > Results")
        table = Table(title=f"扫描结果（已选 {len(sel)} / {len(items)}）", border_style=C_BORDER)
        table.add_column("#", justify="right", style=C_DIM)
        table.add_column("选", justify="center")
        table.add_column("专辑")
        selected_set = set(sel.selected_indices(len(items)))
        for idx, item in enumerate(items, start=1):
            mark = "✓" if (idx - 1) in selected_set else ""
            table.add_row(str(idx), f"[{C_OK}]{mark}[/{C_OK}]" if mark else "", item.label)
        console.print(table)
        console.print(f"[{C_DIM}]a 全选 | c 清空 | x 序号切换 | g 操作 | b 返回[/]")
        raw = (console.input("输入: ") or "").strip().lower()
        if raw in {"b", "back", "q", "0"}:
            return
        if raw == "a":
            sel.select_all(len(items)); continue
        if raw == "c":
            sel.clear(); continue
        if raw.startswith("x"):
            rest = raw[1:].strip() or (console.input("切换序号: ") or "").strip()
            from qdp.ui_compound import parse_toggle_indices
            for i in parse_toggle_indices(rest):
                sel.toggle(i, count=len(items))
            continue
        if raw == "g":
            selected = sel.selected_items(items)
            action = choose_action(console, console.input, selected, allow_rename=True)
            if not action:
                continue
            options: Dict[str, object] = {}
            if action == CompoundAction.RENAME_LIBRARY:
                dry = (console.input("dry-run? Y/n (默认 Y): ") or "").strip().lower()
                options['dry_run'] = False if dry in {'n', 'no'} else True
                options['album_keys'] = [it.payload.get('album_key') for it in selected]
            if action == CompoundAction.EXPORT_REPORT:
                options['filename'] = (console.input("导出文件名(默认 qdp-report.json): ") or "").strip() or 'qdp-report.json'
            plan = build_plan(action, selected, options=options)
            if not confirm_execution(console, plan, console.input):
                continue
            run_plan(console, qobuz, plan)
            _pause(console)


def _normalize_proxies_input(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        return ''
    proxy_list = []
    for proxy in raw.split(','):
        proxy = proxy.strip().rstrip('/')
        if proxy and not proxy.startswith('http'):
            proxy = 'https://' + proxy
        if proxy:
            proxy_list.append(proxy)
    return ','.join(proxy_list)


def _test_all_proxies(console: Console, proxies: list):
    """Test all proxies concurrently via HTTP GET and record results."""
    import time as _time
    import requests as _requests
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
    from qdp.proxy_stats import record_test_result

    _UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    results: Dict[str, tuple] = {}

    def _test_one(url):
        try:
            start = _time.monotonic()
            resp = _requests.get(url.rstrip('/') + '/', timeout=10, headers={"User-Agent": _UA})
            latency_ms = (_time.monotonic() - start) * 1000
            ok = 200 <= resp.status_code < 500
            return url, ok, latency_ms
        except Exception:
            return url, False, 0.0

    with Progress(
        SpinnerColumn(),
        TextColumn(f'[{C_DIM}]{{task.description}}[/{C_DIM}]'),
        BarColumn(bar_width=20),
        TextColumn(f'[{C_DIM}]{{task.completed}}/{{task.total}}[/{C_DIM}]'),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task('测试代理连通性...', total=len(proxies))
        with ThreadPoolExecutor(max_workers=min(10, len(proxies))) as executor:
            futures = {executor.submit(_test_one, p): p for p in proxies}
            for future in as_completed(futures):
                url, ok, latency_ms = future.result()
                try:
                    record_test_result(url, ok, latency_ms)
                except Exception:
                    pass
                results[url] = (ok, latency_ms)
                progress.advance(task)

    # Summary
    ok_count = sum(1 for ok, _ in results.values() if ok)
    console.print(f'[{C_OK}]测试完成: {ok_count}/{len(proxies)} 可用[/]')
    for url, (ok, latency_ms) in results.items():
        status = f'[{C_OK}]✓[/{C_OK}]' if ok else '[red]✗[/red]'
        lat = f'{latency_ms:.0f}ms' if latency_ms > 0 else '--'
        console.print(f'  {status} {url}  [{C_DIM}]{lat}[/{C_DIM}]')
    _pause(console)


def _ui_proxy_pool_editor(console: Console, working: Dict[str, str]) -> bool:
    changed = False
    while True:
        proxies = [p.strip() for p in (working.get('proxies', '') or '').split(',') if p.strip()]
        console.clear(); _header(console, breadcrumb='Dashboard > Settings > Proxy Pool')

        # Load persistent stats
        try:
            from qdp.proxy_stats import load_stats as _load_stats
            all_stats = _load_stats()
        except Exception:
            all_stats = {}

        table = Table(title='代理池', border_style=C_BORDER)
        table.add_column('编号', justify='right', style=C_DIM)
        table.add_column('节点')
        table.add_column('状态', justify='center')
        table.add_column('延迟', justify='right')
        table.add_column('成功率', justify='right')
        table.add_column('最后检查', style=C_DIM)
        if proxies:
            for idx, proxy in enumerate(proxies, start=1):
                stat = all_stats.get(proxy)
                if stat and stat.total > 0:
                    if stat.success_rate >= 0.8:
                        status = f'[{C_OK}]✓[/{C_OK}]'
                    elif stat.success_rate >= 0.5:
                        status = f'[{C_WARN}]![{C_WARN}]'
                    else:
                        status = '[red]✗[/red]'
                    latency = f'{stat.avg_latency_ms:.0f}ms' if stat.avg_latency_ms > 0 else '--'
                    rate = f'{stat.success_rate * 100:.1f}%'
                    last_check = stat.last_success or stat.last_failure or '--'
                    if last_check != '--' and 'T' in last_check:
                        last_check = last_check.split('T')[1]
                else:
                    status = f'[{C_DIM}]--[/{C_DIM}]'
                    latency = '--'
                    rate = '--'
                    last_check = '--'
                table.add_row(str(idx), proxy, status, latency, rate, last_check)
        else:
            table.add_row('-', '当前没有代理节点，默认直连', '', '', '', '')
        console.print(table)
        console.print(f'[{C_DIM}]a 新增 | d 删除 | c 清空 | t 测试全部 | b 返回[/]')
        choice = (console.input('选择: ') or '').strip().lower()
        if choice in {'b', 'q', '0'}:
            return changed
        if choice == 'a':
            raw = (console.input('输入代理节点/域名: ') or '').strip()
            normalized = _normalize_proxies_input(raw)
            if not normalized:
                continue
            for item in [p for p in normalized.split(',') if p.strip()]:
                if item not in proxies:
                    proxies.append(item)
                    changed = True
            working['proxies'] = ','.join(proxies)
            continue
        if choice == 'c':
            if proxies and (console.input('确认清空全部代理? y/N: ') or '').strip().lower() in {'y', 'yes'}:
                working['proxies'] = ''
                changed = True
            continue
        if choice == 'd':
            target = (console.input('输入要删除的序号(可逗号分隔): ') or '').strip()
            if not target:
                continue
            try:
                remove_indices = sorted({int(x.strip()) for x in target.split(',') if x.strip().isdigit()}, reverse=True)
            except Exception:
                remove_indices = []
            touched = False
            for idx in remove_indices:
                if 1 <= idx <= len(proxies):
                    proxies.pop(idx - 1)
                    touched = True
            if touched:
                working['proxies'] = ','.join(proxies)
                changed = True
            continue
        if choice == 't':
            if not proxies:
                console.print('[yellow]没有代理可测试。[/]')
                _pause(console)
                continue
            _test_all_proxies(console, proxies)
            continue


def _ui_settings_editor(console: Console, defaults: Dict[str, str]) -> bool:
    editable_keys = [
        ('default_folder', '下载目录'), ('folder_format', '专辑命名'), ('track_format', '曲目命名'), ('default_quality', '默认画质'),
        ('workers', 'workers'), ('prefetch_workers', 'prefetch_workers(空=跟随)'), ('url_rate', 'url_rate'),
        ('timeout', 'timeout'), ('max_retries', 'max_retries'), ('force_proxy', 'force_proxy(true/false)')
    ]
    working = dict(defaults)
    while True:
        console.clear(); _header(console, breadcrumb='Dashboard > Settings')
        table = Table(title='设置编辑器', border_style=C_BORDER)
        table.add_column('编号', justify='right', style=C_DIM)
        table.add_column('字段')
        table.add_column('当前值')
        for idx, (key, label) in enumerate(editable_keys, start=1):
            table.add_row(str(idx), f"{label} ({key})", str(working.get(key, '')))
        proxy_count = len([p for p in (working.get('proxies', '') or '').split(',') if p.strip()])
        table.add_row('m', f'代理池管理 (proxies)', f'{proxy_count} 个节点')
        table.add_row('p', '预览', '')
        table.add_row('r', '重置配置 (= qdp -r)', '')
        table.add_row('s', '保存', '')
        table.add_row('b', '返回(不保存)', '')
        console.print(table)
        choice = (console.input('选择: ') or '').strip().lower()
        if choice in {'b', 'q', '0'}:
            return False
        if choice == 'm':
            _ui_proxy_pool_editor(console, working)
            continue
        if choice == 'p':
            from qdp.config import build_config_preview
            console.print(Panel.fit(build_config_preview(working), title='配置预览', border_style=C_BORDER)); _pause(console); continue
        if choice == 'r':
            console.print('[yellow]即将进入完整配置向导，这和 qdp -r 一样。当前未保存的设置会丢失。[/]')
            if (console.input('继续? y/N: ') or '').strip().lower() not in {'y', 'yes'}:
                continue
            run_config_wizard(console=console, config_file=CONFIG_FILE)
            defaults.update(load_config_defaults(CONFIG_FILE))
            console.print('[green]已按重置向导更新配置。[/]')
            _pause(console)
            return True
        if choice == 's':
            from qdp.config import build_config_preview
            console.print(Panel.fit(build_config_preview(working), title='保存前预览', border_style=C_BORDER))
            console.print('确认保存? y/N')
            if (console.input('确认: ') or '').strip().lower() not in {'y', 'yes'}:
                continue
            config = load_config(CONFIG_FILE)
            if 'DEFAULT' not in config:
                config['DEFAULT'] = {}
            for key, value in working.items():
                config['DEFAULT'][key] = str(value)
            save_config(config, CONFIG_FILE)
            defaults.update(working)
            console.print('[green]已保存。[/]'); _pause(console); return True
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(editable_keys):
                key, label = editable_keys[idx-1]
                new_value = (console.input(f'{label} ({key}) 新值: ') or '').strip()
                if new_value != '':
                    working[key] = new_value
                continue


def run_ui(argv_entry: str = 'qdp'):
    console = Console()
    initial_checks(console=console, config_file=CONFIG_FILE)
    defaults = load_config_defaults(CONFIG_FILE)
    qobuz = build_qobuz_from_defaults(defaults)
    try:
        initialize_qobuz_client(qobuz, defaults)
    except AppSecretValidationProxyError as exc:
        console.print(f"\n[red]⚠ 登录失败:[/] {exc}")
        console.print("[yellow]当前更像是 Worker / 代理链路异常，不建议立刻运行 qdp -r。[/]")
        console.print("[yellow]请优先检查代理池、Worker、网络环境，然后再重试。[/]")
        console.print("[1] 重新配置  [2] 重试登录  [0] 退出")
        choice = (console.input("请选择: ") or "").strip()
        if choice == "1":
            try:
                run_config_wizard(console=console, config_file=CONFIG_FILE)
                defaults = load_config_defaults(CONFIG_FILE)
                qobuz = build_qobuz_from_defaults(defaults)
                initialize_qobuz_client(qobuz, defaults)
            except AppSecretValidationProxyError as exc2:
                console.print(f"[red]配置后仍然失败：[/]{exc2}")
                console.print("[yellow]这依然更像代理/Worker 问题，不是账号信息本身错误。[/]")
                return
            except (AuthenticationError, InvalidAppIdError, InvalidAppSecretError):
                console.print("[red]配置后仍然登录失败。请检查账号信息或凭证是否正确。[/]")
                return
            except Exception as exc2:
                console.print(f"[red]网络异常：[/]{exc2}")
                console.print("[yellow]配置已保存。请检查网络后重新运行 qdp。[/]")
                return
        elif choice == "2":
            try:
                initialize_qobuz_client(qobuz, defaults)
            except AppSecretValidationProxyError as exc2:
                console.print(f"[red]重试仍然失败：[/]{exc2}")
                console.print("[yellow]当前仍像代理/Worker 对播放授权接口的拦截，不是单纯账号错误。[/]")
                return
            except (AuthenticationError, InvalidAppIdError, InvalidAppSecretError):
                console.print("[red]重试仍然失败。请检查账号信息或凭证。[/]")
                return
            except Exception as exc2:
                console.print(f"[red]网络异常：[/]{exc2}")
                console.print("[yellow]请检查网络后重新运行 qdp。[/]")
                return
        else:
            return
    except (AuthenticationError, InvalidAppIdError, InvalidAppSecretError) as exc:
        console.print(f"\n[red]⚠ 登录失败:[/] {exc}")
        console.print("[yellow]这更像是凭证/App Secret 本身问题，可考虑运行 qdp -r。[/]")
        console.print("[1] 重新配置  [2] 重试登录  [0] 退出")
        choice = (console.input("请选择: ") or "").strip()
        if choice == "1":
            try:
                run_config_wizard(console=console, config_file=CONFIG_FILE)
                defaults = load_config_defaults(CONFIG_FILE)
                qobuz = build_qobuz_from_defaults(defaults)
                initialize_qobuz_client(qobuz, defaults)
            except Exception as exc2:
                console.print(f"[red]配置后仍然失败：[/]{exc2}")
                return
        elif choice == "2":
            try:
                initialize_qobuz_client(qobuz, defaults)
            except Exception as exc2:
                console.print(f"[red]重试仍然失败：[/]{exc2}")
                return
        else:
            return
    except Exception as exc:
        console.print(f"\n[red]⚠ 网络异常：[/]{exc}")
        console.print("[yellow]配置已保存。请检查网络连接后重新运行 qdp。[/]")
        return
    _menu(console, breadcrumb=argv_entry, qobuz=qobuz, defaults=defaults)

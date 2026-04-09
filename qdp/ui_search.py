from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from rich.console import Console
from rich.table import Table

from qdp.ui_compound import CompoundAction, parse_toggle_indices
from qdp.ui_models import SelectionSet, UIItem, UIItemKind

C_DIM = "#9ca3af"
C_OK = "#10b981"
C_BORDER = "#4b5563"


@dataclass
class SearchSelectionResult:
    action: CompoundAction
    items: List[UIItem]
    options: Dict[str, object]


def _make_url_from_item(search_type: str, item: dict) -> str:
    item_type = "artist" if search_type == "artist" else search_type
    return f"https://open.qobuz.com/{item_type}/{item['id']}"


def _build_ui_items(search_type: str, selected_items: List[dict]) -> List[UIItem]:
    urls = []
    for item in selected_items:
        url = _make_url_from_item(search_type, item)
        urls.append(UIItem(kind=UIItemKind.URL, label=url, payload={"url": url}))
    return urls


def interactive_search_compound(
    console: Console,
    client,
    initial_query: str,
    search_type: str,
    limit: int,
) -> Optional[SearchSelectionResult]:
    """Interactive search UI with multi-select and compound operations.

    Returns a SearchSelectionResult (action + items) when user is ready to execute.
    Returns None if user quits/cancels.

    Shortcuts (kept / upgraded):
      - n/p/r//q/Enter
      - a: select all on current page
      - c: clear selection
      - x: toggle selection by index list
      - g: go to operation selector for current selection
      - number list: immediate plan with default action=download (still requires confirm in caller)
    """

    from qdp.ui_compound import choose_action

    query = initial_query
    offset = 0
    selection = SelectionSet()

    while True:
        api_type = search_type + "s"
        data = client.api_call("catalog/search", query=query, type=api_type, limit=limit, offset=offset)
        items = data.get(api_type, {}).get("items", [])

        table = Table(title=f"搜索结果: {query} ({search_type})", title_style=C_DIM, border_style=C_BORDER)
        table.add_column("序号", justify="right", style=C_DIM, no_wrap=True)
        table.add_column("选", justify="center")
        table.add_column("标题")
        table.add_column("艺术家")
        if search_type in ("album", "track"):
            table.add_column("规格", justify="center")
            table.add_column("年份", justify="center", style=C_DIM)

        selected_set = set(selection.selected_indices(len(items)))
        for idx, item in enumerate(items, start=1):
            title = item.get("title", "Unknown")
            if item.get("version"):
                title += f" ({item['version']})"
            artist = (
                item.get("name", "Unknown")
                if search_type == "artist"
                else item.get("artist", {}).get("name") or item.get("performer", {}).get("name", "Unknown")
            )
            mark = "✓" if (idx - 1) in selected_set else ""
            row_data = [str(idx), f"[{C_OK}]{mark}[/{C_OK}]" if mark else "", title, artist]
            if search_type in ("album", "track"):
                if not item.get("streamable"):
                    quality_str = "不可用"
                else:
                    bit_depth = item.get("maximum_bit_depth", 16)
                    sample_rate = item.get("maximum_sampling_rate", 44.1)
                    quality_str = f"{bit_depth}-Bit / {sample_rate} kHz"
                date_str = item.get("release_date_original", "")[:4] if search_type == "album" else ""
                row_data.extend([quality_str, date_str])
            table.add_row(*row_data)

        console.clear()
        console.print(table)
        console.print(
            f"[{C_DIM}]已选 {len(selection)} | n 下一页 | p 上一页 | r 刷新 | / 新关键词 | a 全选 | c 清空 | x 切换选择 | g 操作 | q 退出[/]"
        )
        raw = (console.input("输入: ") or "").strip().lower()

        if raw in {"q", "0"}:
            return None
        if raw == "n":
            offset += limit
            continue
        if raw == "p":
            offset = max(0, offset - limit)
            continue
        if raw in {"r", ""}:
            continue
        if raw == "/":
            new_query = console.input("输入新关键词: ").strip()
            if new_query:
                query = new_query
                offset = 0
                selection.clear()
            continue
        if raw == "a":
            selection.select_all(len(items))
            continue
        if raw == "c":
            selection.clear()
            continue
        if raw.startswith("x"):
            rest = raw[1:].strip() or (console.input("切换序号(逗号/空格分隔): ") or "").strip()
            for i in parse_toggle_indices(rest):
                selection.toggle(i, count=len(items))
            continue
        if raw == "g":
            selected_dicts = selection.selected_items(items)
            chosen = _build_ui_items(search_type, selected_dicts)
            action = choose_action(console, console.input, chosen, allow_rename=False)
            if not action:
                continue
            options: Dict[str, object] = {}
            if action == CompoundAction.EXPORT_REPORT:
                options["filename"] = (console.input("导出文件名(默认 qdp-report.json): ") or "").strip() or "qdp-report.json"
            return SearchSelectionResult(action=action, items=chosen, options=options)

        # Compatibility: numeric selection triggers default download plan (still requires confirm)
        if raw.replace(",", "").isdigit():
            selected_indices = [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]
            chosen_dicts = []
            for index in selected_indices:
                if not (1 <= index <= len(items)):
                    continue
                chosen_dicts.append(items[index - 1])
            chosen = _build_ui_items(search_type, chosen_dicts)
            if chosen:
                return SearchSelectionResult(action=CompoundAction.DOWNLOAD, items=chosen, options={})


__all__ = ["interactive_search_compound", "SearchSelectionResult"]

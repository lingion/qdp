from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from qdp.ui_models import UIItem, UIItemKind


class CompoundAction(str, Enum):
    CHECK_ONLY = "check-only"
    VERIFY_REPAIR = "verify/repair"
    DOWNLOAD = "download"
    RENAME_LIBRARY = "rename-library"
    EXPORT_REPORT = "export-report"


@dataclass
class ExecutionPlan:
    action: CompoundAction
    items: List[UIItem]
    options: Dict[str, object]

    def to_report_dict(self) -> Dict:
        return {
            "action": self.action.value,
            "count": len(self.items),
            "items": [item.to_report_dict() for item in self.items],
            "options": self.options,
        }


def parse_toggle_indices(raw: str) -> List[int]:
    """Parse user input like '1,2 5' to 0-based indices."""
    raw = (raw or "").strip()
    if not raw:
        return []
    tokens = raw.replace(",", " ").split()
    indices = []
    for token in tokens:
        if token.isdigit():
            idx = int(token)
            if idx <= 0:
                continue
            indices.append(idx - 1)
    return indices


def build_plan(action: CompoundAction, selected: Sequence[UIItem], options: Optional[Dict[str, object]] = None) -> ExecutionPlan:
    return ExecutionPlan(action=action, items=list(selected), options=dict(options or {}))


def render_plan(plan: ExecutionPlan) -> Table:
    table = Table(title=f"执行计划: {plan.action.value}", border_style="#4b5563")
    table.add_column("#", justify="right")
    table.add_column("类型")
    table.add_column("目标")
    for idx, item in enumerate(plan.items, start=1):
        label = item.label
        if len(label) > 60:
            label = label[:59] + "…"
        table.add_row(str(idx), item.kind.value, label)
    return table


def confirm_execution(
    console: Console,
    plan: ExecutionPlan,
    input_fn: Callable[[str], str],
) -> bool:
    console.print(render_plan(plan))
    console.print("[bold]确认执行?[/] [green]y[/]/n (默认 n)")
    raw = (input_fn("确认: ") or "").strip().lower()
    return raw in {"y", "yes"}


def export_report(plan: ExecutionPlan, filename: str) -> str:
    payload = plan.to_report_dict()
    path = os.path.abspath(filename)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return path


def run_plan(
    console: Console,
    qobuz,
    plan: ExecutionPlan,
) -> Dict[str, object]:
    """Execute plan using provided QobuzDL instance.

    Returns summary stats.
    """

    stats = {"action": plan.action.value, "total": len(plan.items), "ok": 0, "failed": 0, "skipped": 0}

    # export is pure
    if plan.action == CompoundAction.EXPORT_REPORT:
        target = str(plan.options.get("filename") or "qdp-report.json")
        export_report(plan, target)
        stats["ok"] = len(plan.items)
        return stats

    if plan.action == CompoundAction.CHECK_ONLY:
        qobuz.check_only = True
        qobuz.verify_existing = False
    elif plan.action == CompoundAction.VERIFY_REPAIR:
        qobuz.check_only = False
        qobuz.verify_existing = True
    elif plan.action == CompoundAction.DOWNLOAD:
        qobuz.check_only = False
        qobuz.verify_existing = False

    if plan.action == CompoundAction.RENAME_LIBRARY:
        dry_run = bool(plan.options.get("dry_run", True))
        album_keys = plan.options.get("album_keys")
        qobuz.rename_library(dry_run=dry_run, album_keys=album_keys)
        stats["ok"] = len(plan.items)
        return stats

    # URL actions can be batched.
    if plan.action in {CompoundAction.DOWNLOAD, CompoundAction.CHECK_ONLY, CompoundAction.VERIFY_REPAIR}:
        urls = [item.payload.get("url") for item in plan.items if item.kind == UIItemKind.URL and item.payload.get("url")]
        if urls:
            try:
                qobuz.download_list_of_urls(urls)
                stats["ok"] += len(urls)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                console.print(Panel.fit(f"批量执行失败: {escape(str(exc))}", title="错误", border_style="red"))
                stats["failed"] += len(urls)
        # Any non-url items are skipped for these actions.
        stats["skipped"] += len([it for it in plan.items if it.kind != UIItemKind.URL])
        return stats

    for item in plan.items:
        try:
            if item.kind == UIItemKind.LIBRARY_ALBUM:
                stats["skipped"] += 1
                continue
            stats["skipped"] += 1
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            console.print(Panel.fit(f"执行失败: {escape(item.label)}\n{escape(str(exc))}", title="错误", border_style="red"))
            stats["failed"] += 1
    return stats


def choose_action(
    console: Console,
    input_fn: Callable[[str], str],
    selected: Sequence[UIItem],
    allow_rename: bool = False,
) -> Optional[CompoundAction]:
    """Simple operation selector."""

    if not selected:
        console.print("[yellow]当前没有选中任何条目。[/]")
        return None

    rows: List[Tuple[str, str, CompoundAction]] = [
        ("1", "check-only（只校验不下载）", CompoundAction.CHECK_ONLY),
        ("2", "verify/repair（校验 + 补齐）", CompoundAction.VERIFY_REPAIR),
        ("3", "download（下载）", CompoundAction.DOWNLOAD),
    ]
    if allow_rename:
        rows.append(("4", "rename-library（重命名本地库）", CompoundAction.RENAME_LIBRARY))
        rows.append(("5", "export report（导出报告 JSON）", CompoundAction.EXPORT_REPORT))
    else:
        rows.append(("4", "export report（导出报告 JSON）", CompoundAction.EXPORT_REPORT))

    table = Table(title=f"操作选择器（已选 {len(selected)} 项）", border_style="#4b5563")
    table.add_column("编号", justify="right")
    table.add_column("操作")
    for code, label, _action in rows:
        table.add_row(code, label)
    console.print(table)
    console.print("输入编号执行；b 返回；q 取消")
    raw = (input_fn("选择: ") or "").strip().lower()
    if raw in {"q", "0"}:
        return None
    if raw in {"b", "back"}:
        return None
    for code, _, action in rows:
        if raw == code:
            return action
    console.print("[red]无效选择。[/]")
    return None

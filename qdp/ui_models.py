from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


class UIItemKind(str, Enum):
    URL = "url"  # any qobuz url
    LIBRARY_ALBUM = "library_album"  # local library album dir candidate


@dataclass(frozen=True)
class UIItem:
    kind: UIItemKind
    label: str
    payload: Dict[str, Any]

    def to_report_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "label": self.label,
            "payload": self.payload,
        }


class SelectionSet:
    """Stable multi-selection for a list UI.

    Tracks selected item indices (0-based) and can toggle selections.
    """

    def __init__(self):
        self._selected: Set[int] = set()

    def clear(self):
        self._selected.clear()

    def select_all(self, count: int):
        self._selected = set(range(max(0, int(count))))

    def toggle(self, idx: int, count: Optional[int] = None) -> bool:
        idx = int(idx)
        if count is not None and not (0 <= idx < int(count)):
            return False
        if idx in self._selected:
            self._selected.remove(idx)
        else:
            self._selected.add(idx)
        return True

    def set_selected(self, indices: Iterable[int], count: Optional[int] = None):
        new_selected = set()
        for idx in indices:
            try:
                idx = int(idx)
            except Exception:
                continue
            if count is not None and not (0 <= idx < int(count)):
                continue
            new_selected.add(idx)
        self._selected = new_selected

    def selected_indices(self, count: Optional[int] = None) -> List[int]:
        if count is None:
            return sorted(self._selected)
        return sorted(i for i in self._selected if 0 <= i < int(count))

    def selected_items(self, items: Sequence[Any]) -> List[Any]:
        return [items[i] for i in self.selected_indices(len(items))]

    def __len__(self) -> int:
        return len(self._selected)

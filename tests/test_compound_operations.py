import unittest
from unittest.mock import patch

from rich.console import Console

from qdp.ui_compound import CompoundAction, build_plan, confirm_execution, parse_toggle_indices
from qdp.ui_models import SelectionSet, UIItem, UIItemKind


class CompoundOperationParseTests(unittest.TestCase):
    def test_parse_toggle_indices(self):
        self.assertEqual(parse_toggle_indices(""), [])
        self.assertEqual(parse_toggle_indices("1"), [0])
        self.assertEqual(parse_toggle_indices("1,2 5"), [0, 1, 4])
        self.assertEqual(parse_toggle_indices("0 2"), [1])

    def test_selection_set_toggle_and_clear(self):
        sel = SelectionSet()
        sel.toggle(0, count=3)
        sel.toggle(2, count=3)
        self.assertEqual(sel.selected_indices(), [0, 2])
        sel.toggle(2, count=3)
        self.assertEqual(sel.selected_indices(), [0])
        sel.clear()
        self.assertEqual(len(sel), 0)

    def test_build_plan_and_confirm(self):
        items = [
            UIItem(kind=UIItemKind.URL, label="u1", payload={"url": "https://open.qobuz.com/album/1"}),
            UIItem(kind=UIItemKind.URL, label="u2", payload={"url": "https://open.qobuz.com/album/2"}),
        ]
        plan = build_plan(CompoundAction.DOWNLOAD, items, options={"foo": "bar"})
        self.assertEqual(plan.action, CompoundAction.DOWNLOAD)
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(plan.options["foo"], "bar")

        console = Console()
        with patch("builtins.input", return_value="y"):
            ok = confirm_execution(console, plan, input_fn=lambda prompt="": "y")
        self.assertTrue(ok)

        ok2 = confirm_execution(console, plan, input_fn=lambda prompt="": "n")
        self.assertFalse(ok2)


if __name__ == "__main__":
    unittest.main()

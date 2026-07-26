import os
import tkinter as tk
import unittest
from tkinter import ttk

from autocomplete import AutocompleteCombobox, filter_suggestions, normalize_search_text


def _display_available() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        probe = tk.Tk()
    except tk.TclError:
        return False
    probe.destroy()
    return True


class AutocompleteFilterTests(unittest.TestCase):
    def test_normalizes_case_accents_and_spaces(self):
        self.assertEqual(normalize_search_text("  TôKAI   Teiô "), "tokai teio")

    def test_matches_all_tokens_in_any_position(self):
        values = [
            "Tokai Teio — Beyond the Horizon",
            "Special Week — Special Dreamer",
            "Teio Tokai — Alternative",
        ]
        self.assertEqual(
            filter_suggestions("teio horizon", values),
            ["Tokai Teio — Beyond the Horizon"],
        )

    def test_prefix_matches_are_ranked_before_contains_matches(self):
        values = ["Mejiro McQueen", "Oguri Cap — Mejiro reference", "Mejiro Dober"]
        self.assertEqual(
            filter_suggestions("mejiro", values),
            ["Mejiro Dober", "Mejiro McQueen", "Oguri Cap — Mejiro reference"],
        )

    def test_empty_query_returns_alphabetical_limited_suggestions(self):
        self.assertEqual(filter_suggestions("", ["C", "A", "B"], limit=2), ["A", "B"])

    def test_deduplicates_values(self):
        self.assertEqual(filter_suggestions("rice", ["Rice Shower", "Rice Shower"]), ["Rice Shower"])


@unittest.skipUnless(_display_available(), "needs a display")
class AutocompletePopupLifecycleTests(unittest.TestCase):
    """Regression tests for a popup that would not stay closed.

    Accepting a value called focus_set() on the field, whose FocusIn handler
    refreshed the list; since an exact value shows the full list, the popup
    reopened right after every pick and scrolled to the accepted row."""

    def setUp(self) -> None:
        self.root = tk.Tk()
        self.values = [f"Uma {index:02d}" for index in range(40)]
        self.combo = ttk.Combobox(self.root, values=self.values)
        self.combo.pack()
        self.elsewhere = ttk.Button(self.root, text="Elsewhere")
        self.elsewhere.pack()
        self.root.update()
        self.controller = AutocompleteCombobox(
            self.combo, lambda: self.values, max_suggestions=8
        )

    def tearDown(self) -> None:
        self.root.destroy()

    def _settle(self) -> None:
        self.root.update()
        self.root.update_idletasks()

    def _open(self, text: str = "Uma") -> None:
        self.controller._suppress_open = False
        self.combo.focus_set()
        self.combo.delete(0, tk.END)
        self.combo.insert(0, text)
        self.controller.refresh(force=True)
        self._settle()

    def test_picking_a_value_closes_and_stays_closed(self) -> None:
        self._open()
        self.assertTrue(self.controller._is_open())
        expected = self.controller.listbox.get(3)
        event = type("Event", (), {"y": self.controller.listbox.bbox(3)[1]})()
        self.controller._accept_click(event)
        self._settle()
        self.assertFalse(self.controller._is_open())
        self.assertEqual(self.combo.get(), expected)
        self.combo.focus_set()
        self._settle()
        self.assertFalse(self.controller._is_open())

    def test_outside_click_closes_and_stays_closed(self) -> None:
        self._open()
        event = type("Event", (), {"widget": self.elsewhere})()
        self.controller._on_toplevel_click(event)
        self._settle()
        self.assertFalse(self.controller._is_open())
        self.combo.focus_set()
        self._settle()
        self.assertFalse(self.controller._is_open())

    def test_click_inside_the_list_does_not_close_early(self) -> None:
        self._open()
        event = type("Event", (), {"widget": self.controller.listbox})()
        self.controller._on_toplevel_click(event)
        self._settle()
        self.assertTrue(self.controller._is_open())

    def test_typing_does_not_scroll_the_list_on_its_own(self) -> None:
        self._open("Uma")
        self.controller._set_active(30)
        self._settle()
        before = self.controller.listbox.yview()[0]
        self.combo.insert(tk.END, " 3")
        self.controller._suppress_open = False
        self.controller.refresh(force=True)
        self._settle()
        self.assertLessEqual(self.controller.listbox.yview()[0], before)

    def test_keyboard_navigation_keeps_the_active_row_visible(self) -> None:
        self._open("Uma")
        self.controller._set_active(0)
        self._settle()
        for _ in range(12):
            self.controller._move_selection_down()
        self._settle()
        active = self.controller._active_index()
        self.assertEqual(active, 12)
        first, last = self.controller.listbox.yview()
        total = self.controller.listbox.size()
        self.assertGreater(first, 0)
        self.assertLessEqual(first * total, active)
        self.assertLessEqual(active, last * total)

    def test_escape_closes_until_a_deliberate_action(self) -> None:
        self._open()
        self.controller._on_escape()
        self._settle()
        self.assertFalse(self.controller._is_open())
        self.combo.focus_set()
        self._settle()
        self.assertFalse(self.controller._is_open())
        self.controller._on_field_click()
        self._settle()
        self.assertTrue(self.controller._is_open())

    def test_typing_reopens_after_a_dismissal(self) -> None:
        self._open()
        self.controller._on_escape()
        self._settle()
        self.combo.delete(0, tk.END)
        self.combo.insert(0, "Uma 0")
        self.controller._on_key_release(type("Event", (), {"keysym": "0"})())
        self._settle()
        self.assertTrue(self.controller._is_open())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk


def normalize_search_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(text.casefold().split())


def filter_suggestions(query: object, values: Iterable[object], limit: int = 12) -> list[str]:
    query_text = normalize_search_text(query)
    tokens = query_text.split()
    ranked: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()

    for raw_value in values:
        value = str(raw_value)
        if value in seen:
            continue
        seen.add(value)
        normalized = normalize_search_text(value)
        if tokens and not all(token in normalized for token in tokens):
            continue

        if not query_text:
            rank = 3
            position = 0
        elif normalized == query_text:
            rank = 0
            position = 0
        elif normalized.startswith(query_text):
            rank = 1
            position = 0
        else:
            rank = 2
            position = min((normalized.find(token) for token in tokens), default=0)
        ranked.append((rank, position, normalized, value))

    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in ranked[: max(1, int(limit))]]


class AutocompleteCombobox:
    """Attach an inline suggestion popup to an editable ttk.Combobox."""

    def __init__(
        self,
        combo: ttk.Combobox,
        values_getter: Callable[[], Iterable[object]],
        *,
        max_suggestions: int = 12,
    ) -> None:
        self.combo = combo
        self.values_getter = values_getter
        self.max_suggestions = max_suggestions
        self.popup: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self._after_id: str | None = None

        combo.bind("<KeyRelease>", self._on_key_release, add="+")
        combo.bind("<FocusIn>", self._schedule_refresh, add="+")
        combo.bind("<Button-1>", self._schedule_refresh, add="+")
        combo.bind("<Down>", self._focus_first, add="+")
        combo.bind("<Return>", self._accept_first, add="+")
        combo.bind("<Escape>", self._hide, add="+")
        combo.bind("<FocusOut>", self._schedule_focus_check, add="+")
        combo.bind("<Configure>", self._schedule_refresh, add="+")
        combo.bind("<Destroy>", self._destroy, add="+")

    def refresh(self, *, force: bool = False) -> None:
        if not self.combo.winfo_exists() or str(self.combo.cget("state")) == "disabled":
            self._hide()
            return
        if not force and self.combo.focus_get() not in {self.combo, self.listbox}:
            return

        values = filter_suggestions(
            self.combo.get(),
            self.values_getter() or (),
            limit=self.max_suggestions,
        )
        exact = self.combo.get().strip() in values
        if not values or (exact and len(values) == 1):
            self._hide()
            return

        self._ensure_popup()
        assert self.popup is not None and self.listbox is not None
        self.listbox.delete(0, tk.END)
        for value in values:
            self.listbox.insert(tk.END, value)
        visible_rows = min(len(values), self.max_suggestions)
        self.listbox.configure(height=max(1, visible_rows))
        self._position_popup()
        self.popup.deiconify()
        self.popup.lift()

    def hide(self) -> None:
        self._hide()

    def _ensure_popup(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            return
        popup = tk.Toplevel(self.combo)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)

        listbox = tk.Listbox(
            popup,
            activestyle="dotbox",
            exportselection=False,
            selectmode=tk.SINGLE,
            relief=tk.SOLID,
            borderwidth=1,
        )
        listbox.pack(fill=tk.BOTH, expand=True)
        listbox.bind("<ButtonRelease-1>", self._accept_selected)
        listbox.bind("<Return>", self._accept_selected)
        listbox.bind("<Escape>", self._return_to_combo)
        listbox.bind("<Up>", self._listbox_up)
        listbox.bind("<FocusOut>", self._schedule_focus_check)
        self.popup = popup
        self.listbox = listbox

    def _position_popup(self) -> None:
        if self.popup is None or self.listbox is None:
            return
        self.combo.update_idletasks()
        width = max(self.combo.winfo_width(), 240)
        row_height = max(20, self.listbox.winfo_reqheight() // max(1, int(self.listbox.cget("height"))))
        height = row_height * max(1, int(self.listbox.cget("height"))) + 2
        x = self.combo.winfo_rootx()
        y = self.combo.winfo_rooty() + self.combo.winfo_height()
        self.popup.geometry(f"{width}x{height}+{x}+{y}")

    def _on_key_release(self, event: tk.Event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R"}:
            return
        self.refresh(force=True)

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        self._after_id = self.combo.after_idle(lambda: self.refresh(force=True))

    def _focus_first(self, _event: tk.Event | None = None) -> str | None:
        self.refresh(force=True)
        if self.listbox is None or not self.listbox.size():
            return None
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self.listbox.focus_set()
        return "break"

    def _accept_first(self, _event: tk.Event | None = None) -> str | None:
        if self.listbox is None or not self.listbox.winfo_ismapped() or not self.listbox.size():
            return None
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        return self._accept_selected()

    def _accept_selected(self, _event: tk.Event | None = None) -> str:
        if self.listbox is None:
            return "break"
        selection = self.listbox.curselection()
        if not selection and self.listbox.size():
            selection = (self.listbox.index(tk.ACTIVE),)
        if selection:
            value = self.listbox.get(selection[0])
            self.combo.set(value)
            self.combo.event_generate("<<ComboboxSelected>>")
        self._hide()
        self.combo.focus_set()
        self.combo.icursor(tk.END)
        return "break"

    def _return_to_combo(self, _event: tk.Event | None = None) -> str:
        self._hide()
        self.combo.focus_set()
        return "break"

    def _listbox_up(self, _event: tk.Event | None = None) -> str | None:
        if self.listbox is None:
            return None
        selection = self.listbox.curselection()
        if selection and selection[0] == 0:
            return self._return_to_combo()
        return None

    def _schedule_focus_check(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        self._after_id = self.combo.after(120, self._hide_if_focus_left)

    def _hide_if_focus_left(self) -> None:
        self._after_id = None
        focused = self.combo.focus_get()
        if focused not in {self.combo, self.listbox}:
            self._hide()

    def _hide(self, _event: tk.Event | None = None) -> str | None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.withdraw()
        return "break" if _event is not None else None

    def _cancel_after(self) -> None:
        if self._after_id is not None:
            try:
                self.combo.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _destroy(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None
        self.listbox = None

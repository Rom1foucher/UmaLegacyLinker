from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable
import tkinter as tk
from tkinter import ttk

HARD_RESULT_LIMIT = 400


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
    """Unified search popup for an editable ttk.Combobox.

    - shows every match (scrollable, capped at HARD_RESULT_LIMIT) with a result count
    - Up/Down move the highlight without stealing focus from the entry
    - Return accepts the highlight, Escape closes, click/hover select with the mouse
    - keeps the native dropdown list in sync with the current filter
    """

    def __init__(
        self,
        combo: ttk.Combobox,
        values_getter: Callable[[], Iterable[object]],
        *,
        max_suggestions: int = 12,
        count_formatter: Callable[[int], str] | None = None,
    ) -> None:
        self.combo = combo
        self.values_getter = values_getter
        self.max_visible_rows = max(3, int(max_suggestions))
        self.count_formatter = count_formatter or (lambda total: f"{total} résultats")
        self.popup: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self.count_label: tk.Label | None = None
        self._after_id: str | None = None
        # Set right after a value is accepted (or the popup is dismissed) so the
        # focus/refresh events that follow cannot immediately reopen the list.
        # Cleared by a real keystroke or a deliberate click on the field.
        self._suppress_open = False
        self._toplevel: tk.Misc | None = None
        self._toplevel_configure_bind_id: str | None = None
        self._toplevel_click_bind_id: str | None = None

        combo.bind("<KeyRelease>", self._on_key_release, add="+")
        combo.bind("<FocusIn>", self._on_focus_in, add="+")
        combo.bind("<Button-1>", self._on_field_click, add="+")
        # The widget also has its own native dropdown (the arrow): picking a
        # value there must close our popup instead of reopening it.
        combo.bind("<<ComboboxSelected>>", self._on_native_selection, add="+")
        combo.bind("<Down>", self._move_selection_down, add="+")
        combo.bind("<Up>", self._move_selection_up, add="+")
        combo.bind("<Return>", self._accept_active, add="+")
        combo.bind("<Tab>", self._accept_on_tab, add="+")
        combo.bind("<Escape>", self._on_escape, add="+")
        combo.bind("<FocusOut>", self._schedule_focus_check, add="+")
        combo.bind("<Configure>", self._schedule_reposition, add="+")
        combo.bind("<Destroy>", self._destroy, add="+")

    # ------------------------------------------------------------------ refresh
    def refresh(self, *, force: bool = False) -> None:
        if not self.combo.winfo_exists() or str(self.combo.cget("state")) == "disabled":
            self._hide()
            return
        if self._suppress_open:
            return
        if not force and self.combo.focus_get() is not self.combo:
            return

        all_values = [str(value) for value in (self.values_getter() or ())]
        current_text = self.combo.get()
        # A value already selected in full should not filter the list down to
        # itself: show everything so the next keystroke simply replaces it.
        effective_query = "" if current_text.strip() in all_values else current_text
        matches = filter_suggestions(
            effective_query,
            all_values,
            limit=HARD_RESULT_LIMIT,
        )
        self._sync_native_values(matches)
        if not matches:
            self._hide()
            return

        self._ensure_popup()
        assert self.popup is not None and self.listbox is not None and self.count_label is not None
        previous_active = self._active_value()
        self.listbox.delete(0, tk.END)
        for value in matches:
            self.listbox.insert(tk.END, value)
        if previous_active in matches:
            # No scrolling here: refresh runs on every keystroke, and scrolling
            # to the remembered row would make the list jump on its own.
            self._set_active(matches.index(previous_active), scroll=False)
        visible_rows = min(len(matches), self.max_visible_rows)
        self.listbox.configure(height=max(1, visible_rows))
        self.count_label.configure(text=self.count_formatter(len(matches)))
        self._position_popup()
        self.popup.deiconify()
        self.popup.lift()

    def hide(self) -> None:
        self._hide()

    # ------------------------------------------------------------------- popup
    def _ensure_popup(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            return
        popup = tk.Toplevel(self.combo)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)

        container = tk.Frame(popup, relief=tk.SOLID, borderwidth=1)
        container.pack(fill=tk.BOTH, expand=True)
        listbox = tk.Listbox(
            container,
            activestyle="dotbox",
            exportselection=False,
            selectmode=tk.SINGLE,
            relief=tk.FLAT,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        count_label = tk.Label(container, anchor="e", padx=6)
        count_label.grid(row=1, column=0, columnspan=2, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        listbox.bind("<ButtonRelease-1>", self._accept_click)
        listbox.bind("<Motion>", self._hover_select)
        self.popup = popup
        self.listbox = listbox
        self.count_label = count_label
        self._bind_toplevel_events()

    def _bind_toplevel_events(self) -> None:
        toplevel = self.combo.winfo_toplevel()
        if self._toplevel is toplevel and self._toplevel_configure_bind_id is not None:
            return
        self._unbind_toplevel_events()
        self._toplevel = toplevel
        self._toplevel_configure_bind_id = toplevel.bind("<Configure>", self._schedule_reposition, add="+")
        # Bound on press, not release: this must run and close the popup
        # before the click reaches whatever is underneath it, and before any
        # unrelated widget's own handlers run.
        self._toplevel_click_bind_id = toplevel.bind("<ButtonPress-1>", self._on_toplevel_click, add="+")

    def _unbind_toplevel_events(self) -> None:
        if self._toplevel is not None:
            for event_name, bind_id in (
                ("<Configure>", self._toplevel_configure_bind_id),
                ("<ButtonPress-1>", self._toplevel_click_bind_id),
            ):
                if bind_id is not None:
                    try:
                        self._toplevel.unbind(event_name, bind_id)
                    except tk.TclError:
                        pass
        self._toplevel = None
        self._toplevel_configure_bind_id = None
        self._toplevel_click_bind_id = None

    def _is_descendant(self, widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
        while widget is not None:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _on_toplevel_click(self, event: tk.Event) -> None:
        if not self._is_open():
            return
        clicked = event.widget
        if clicked is self.combo or self._is_descendant(clicked, self.popup):
            return
        # A genuine click elsewhere in the window: close immediately, before
        # that widget processes the same click.
        self._suppress_open = True
        self._hide()

    def _position_popup(self) -> None:
        if self.popup is None or self.listbox is None or self.count_label is None:
            return
        self.combo.update_idletasks()
        self.popup.update_idletasks()
        width = max(self.combo.winfo_width(), 260)
        height = self.listbox.winfo_reqheight() + self.count_label.winfo_reqheight() + 2
        x = self.combo.winfo_rootx()
        y = self.combo.winfo_rooty() + self.combo.winfo_height()
        self.popup.geometry(f"{width}x{height}+{x}+{y}")

    def _is_open(self) -> bool:
        return (
            self.popup is not None
            and self.popup.winfo_exists()
            and self.popup.winfo_ismapped()
            and self.listbox is not None
        )

    # -------------------------------------------------------------- selection
    def _active_index(self) -> int | None:
        if self.listbox is None or not self.listbox.size():
            return None
        selection = self.listbox.curselection()
        if selection:
            return int(selection[0])
        return None

    def _active_value(self) -> str | None:
        index = self._active_index()
        if index is None or self.listbox is None:
            return None
        return str(self.listbox.get(index))

    def _set_active(self, index: int, *, scroll: bool = True) -> None:
        if self.listbox is None or not self.listbox.size():
            return
        index = max(0, min(index, self.listbox.size() - 1))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        if scroll:
            self.listbox.see(index)

    def _move_selection(self, delta: int) -> str | None:
        if not self._is_open():
            self.refresh(force=True)
            if not self._is_open():
                return None
        assert self.listbox is not None
        current = self._active_index()
        if current is None:
            target = 0 if delta > 0 else self.listbox.size() - 1
        else:
            target = (current + delta) % self.listbox.size()
        self._set_active(target)
        return "break"

    def _move_selection_down(self, _event: tk.Event | None = None) -> str | None:
        return self._move_selection(1)

    def _move_selection_up(self, _event: tk.Event | None = None) -> str | None:
        return self._move_selection(-1)

    def _hover_select(self, event: tk.Event) -> None:
        if self.listbox is None or not self.listbox.size():
            return
        self._set_active(self.listbox.nearest(event.y), scroll=False)

    # -------------------------------------------------------------- acceptance
    def _accept_value(self, value: str) -> None:
        self._suppress_open = True
        self.combo.set(value)
        self.combo.icursor(tk.END)
        self._hide()
        # Generated last, and with the popup already closed and locked, so any
        # handler the application attaches cannot bounce the list back open.
        self.combo.event_generate("<<ComboboxSelected>>")

    def _accept_active(self, _event: tk.Event | None = None) -> str | None:
        if not self._is_open():
            return None
        value = self._active_value()
        if value is None and self.listbox is not None and self.listbox.size():
            value = str(self.listbox.get(0))
        if value is None:
            return None
        self._accept_value(value)
        self.combo.focus_set()
        return "break"

    def _accept_on_tab(self, _event: tk.Event | None = None) -> None:
        if not self._is_open():
            return None
        value = self._active_value()
        if value is not None:
            self._accept_value(value)
        else:
            self._hide()
        return None  # let Tab keep its focus-traversal behaviour

    def _accept_click(self, event: tk.Event) -> str:
        if self.listbox is not None and self.listbox.size():
            self._accept_value(str(self.listbox.get(self.listbox.nearest(event.y))))
        self.combo.focus_set()
        return "break"

    # ------------------------------------------------------------------ events
    def _on_key_release(self, event: tk.Event) -> None:
        if event.keysym in {
            "Up", "Down", "Return", "KP_Enter", "Escape", "Tab",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
        }:
            return
        self._suppress_open = False
        self.refresh(force=True)

    def _on_focus_in(self, _event: tk.Event | None = None) -> None:
        """Select the whole content so typing replaces it, without opening the list.

        Opening on focus alone would reopen the popup on the focus_set that
        follows accepting a value, which is what made picking an option leave
        the list open (and scroll it to the accepted row)."""
        try:
            self.combo.selection_range(0, tk.END)
            self.combo.icursor(tk.END)
        except tk.TclError:
            pass

    def _on_field_click(self, _event: tk.Event | None = None) -> None:
        """A click on the field itself is a deliberate request to browse."""
        self._suppress_open = False
        self._schedule_refresh()

    def _on_escape(self, _event: tk.Event | None = None) -> str | None:
        was_open = self._is_open()
        self._suppress_open = True
        self._hide()
        return "break" if was_open else None

    def _on_native_selection(self, _event: tk.Event | None = None) -> None:
        self._suppress_open = True
        self._hide()

    def _schedule_refresh(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        self._after_id = self.combo.after_idle(lambda: self.refresh(force=True))

    def _schedule_reposition(self, _event: tk.Event | None = None) -> None:
        if self._is_open():
            self._position_popup()

    def _schedule_focus_check(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        self._after_id = self.combo.after(120, self._hide_if_focus_left)

    def _hide_if_focus_left(self) -> None:
        self._after_id = None
        focused = self.combo.focus_get()
        if focused is self.combo:
            return
        if self.popup is not None and self._is_descendant(focused, self.popup):
            # Focus moved onto the popup itself (e.g. the listbox took focus
            # on click): the outside-click handler owns closing in that case,
            # not this delayed check, so a pending selection can't be raced.
            return
        self._hide()

    def _sync_native_values(self, matches: list[str]) -> None:
        try:
            # Reconfiguring identical values still re-renders the native
            # dropdown, which can make it scroll while it is open.
            if [str(value) for value in self.combo.cget("values")] == matches:
                return
            self.combo.configure(values=matches)
        except tk.TclError:
            pass

    def _restore_native_values(self) -> None:
        try:
            values = [str(value) for value in (self.values_getter() or ())]
            self.combo.configure(values=values)
        except tk.TclError:
            pass

    def _hide(self, _event: tk.Event | None = None) -> str | None:
        was_open = self._is_open()
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.withdraw()
        if was_open:
            self._restore_native_values()
        return "break" if _event is not None and was_open else None

    def _cancel_after(self) -> None:
        if self._after_id is not None:
            try:
                self.combo.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _destroy(self, _event: tk.Event | None = None) -> None:
        self._cancel_after()
        self._unbind_toplevel_events()
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None
        self.listbox = None
        self.count_label = None

"""Result families as tabs over one shared context.

The workspace used to hold one result slot: every pane lived in a single
`QStackedWidget`, so running any search visually destroyed the previous
result and left the user unable to tell whether it still existed. Worse, both
remote searches shared one pane, so a grandparent search overwrote the parent
results it was meant to complement.

Tabs are the honest control here: these are alternative views of the same
object — one Ace, one profile, one set of conditions — which is exactly what
tabs are for, and what a stack of unrelated screens is not. Each family keeps
its own pane and its own last result, so switching is free and comparing no
longer requires recomputing.

Selecting a tab therefore shows; it never computes. Running is one explicit
verb per view, which replaces the seven-button command surface the two source
cards had grown.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ui_qt.components import muted_label
from ui_qt.context import AppContext

PAIRS = "pairs"
BRANCHES = "branches"
FUTURE = "future"
ONLINE_PARENT = "online_parent"
ONLINE_GP = "online_gp"

# Ordered by frequency: the most used family is first and selected by default.
FAMILY_ORDER = (PAIRS, BRANCHES, FUTURE, ONLINE_PARENT, ONLINE_GP)

LOCAL_FAMILIES = (PAIRS, BRANCHES, FUTURE)
ONLINE_FAMILIES = (ONLINE_PARENT, ONLINE_GP)

# State glyphs stay short so tab labels keep passing the layout audit's
# button-text-width check in both languages. Each is doubled by a tooltip:
# nothing is conveyed by a symbol alone.
STATE_EMPTY = "empty"
STATE_RUNNING = "running"
STATE_READY = "ready"
STATE_STALE = "stale"
STATE_LOADED = "loaded"

STATE_GLYPHS = {
    STATE_EMPTY: "○",
    STATE_RUNNING: "⟳",
    STATE_READY: "●",
    STATE_STALE: "◐",
    STATE_LOADED: "▣",
}

STATE_LABELS = {
    STATE_EMPTY: "Aucun résultat",
    STATE_RUNNING: "Calcul en cours",
    STATE_READY: "Résultat à jour",
    STATE_STALE: "Le contexte a changé depuis ce calcul",
    STATE_LOADED: "Résultat chargé depuis le disque",
}

FAMILY_TITLES = {
    PAIRS: "Paires",
    BRANCHES: "Parents",
    FUTURE: "GP futurs",
    ONLINE_PARENT: "moe · Parents",
    ONLINE_GP: "moe · GP",
}

FAMILY_HINTS = {
    PAIRS: "Les meilleures paires de parents locaux pour l’Ace visé.",
    BRANCHES: "Les meilleurs parents locaux pris individuellement, avec leur branche complète.",
    FUTURE: "Les meilleurs grands-parents locaux pour produire le parent visé.",
    ONLINE_PARENT: "Des parents publics uma.moe combinés à ta collection, classés par le moteur exact local.",
    ONLINE_GP: "Des grands-parents publics uma.moe pour produire le parent visé.",
}

# Short on purpose: the tab already names the subject, so the button only has
# to carry the verb — and a long label crowds the toolbar out at 1120 px.
FAMILY_RUN_LABELS = {
    PAIRS: "Classer",
    BRANCHES: "Classer",
    FUTURE: "Classer",
    ONLINE_PARENT: "Rechercher",
    ONLINE_GP: "Rechercher",
}


class ResultFamilyView(QWidget):
    """One family's pane, plus the empty state shown before its first run.

    A shared placeholder could only say "nothing to show". A per-family one
    can say what this family answers, which is the information a first-time
    user needs at exactly the moment the pane is blank.
    """

    def __init__(self, family: str, pane: QWidget, context: AppContext, parent=None):
        super().__init__(parent)
        self.family = family
        self.pane = pane
        self.context = context
        self.state = STATE_EMPTY
        self.profile: dict[str, Any] = {}
        self.result_kind = ""
        # The fingerprint of the inputs this result was computed from. Empty
        # for a result read from disk: its inputs are unknown, and claiming
        # freshness would be a guess.
        self.fingerprint = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.setContentsMargins(28, 28, 28, 28)
        self.placeholder_title = QLabel("")
        self.placeholder_title.setObjectName("sectionTitle")
        self.placeholder_title.setWordWrap(True)
        self.placeholder_hint = muted_label("")
        placeholder_layout.addStretch(1)
        placeholder_layout.addWidget(self.placeholder_title)
        placeholder_layout.addWidget(self.placeholder_hint)
        placeholder_layout.addStretch(1)
        self.stack.addWidget(placeholder)
        self.stack.addWidget(pane)
        layout.addWidget(self.stack)
        self.retranslate()

    def mark_result(
        self,
        *,
        loaded: bool,
        kind: str,
        profile: dict[str, Any] | None,
        fingerprint: str = "",
    ) -> None:
        self.state = STATE_LOADED if loaded else STATE_READY
        self.result_kind = kind
        self.profile = dict(profile or {})
        self.fingerprint = "" if loaded else fingerprint
        self.stack.setCurrentWidget(self.pane)

    def refresh_freshness(self, fingerprint: str) -> None:
        """Compare the current inputs with the ones this result came from.

        A result loaded from disk keeps its own state: without a known
        fingerprint there is nothing to compare, and calling it stale would be
        as much of a guess as calling it fresh.
        """
        if self.state in {STATE_RUNNING, STATE_EMPTY, STATE_LOADED}:
            return
        if not self.fingerprint:
            return
        self.state = STATE_READY if fingerprint == self.fingerprint else STATE_STALE

    def mark_running(self) -> None:
        self.state = STATE_RUNNING

    def clear_running(self) -> None:
        if self.state == STATE_RUNNING:
            self.state = STATE_EMPTY if self.result_kind == "" else STATE_READY

    def is_stale(self) -> bool:
        return self.state == STATE_STALE

    def has_result(self) -> bool:
        return bool(self.result_kind)

    def retranslate(self) -> None:
        t = self.context.t
        self.placeholder_title.setText(t(FAMILY_TITLES[self.family]))
        self.placeholder_hint.setText(t(FAMILY_HINTS[self.family]))


class ResultFamilyTabs(QWidget):
    """The tab bar plus one persistent view per family."""

    current_changed = Signal(str)

    def __init__(self, context: AppContext, panes: dict[str, QWidget], parent=None):
        super().__init__(parent)
        self.context = context
        self.views: dict[str, ResultFamilyView] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.bar = QTabBar()
        self.bar.setDrawBase(False)
        self.bar.setExpanding(False)
        self.bar.setUsesScrollButtons(True)
        head.addWidget(self.bar)
        head.addStretch(1)
        layout.addLayout(head)

        self.stack = QStackedWidget()
        for family in FAMILY_ORDER:
            view = ResultFamilyView(family, panes[family], context)
            self.views[family] = view
            self.stack.addWidget(view)
            self.bar.addTab("")
        layout.addWidget(self.stack, 1)

        self.bar.currentChanged.connect(self._tab_changed)
        self.bar.setCurrentIndex(0)
        self.retranslate()

    def _tab_changed(self, index: int) -> None:
        if 0 <= index < len(FAMILY_ORDER):
            self.stack.setCurrentIndex(index)
            self.current_changed.emit(FAMILY_ORDER[index])

    def current_family(self) -> str:
        index = self.bar.currentIndex()
        return FAMILY_ORDER[index] if 0 <= index < len(FAMILY_ORDER) else PAIRS

    def set_current_family(self, family: str) -> None:
        if family in FAMILY_ORDER:
            self.bar.setCurrentIndex(FAMILY_ORDER.index(family))

    def view(self, family: str) -> ResultFamilyView:
        return self.views[family]

    def refresh_freshness(self) -> None:
        for family, view in self.views.items():
            view.refresh_freshness(self.context.family_fingerprint(family))
        self.refresh_states()

    def refresh_states(self) -> None:
        t = self.context.t
        for index, family in enumerate(FAMILY_ORDER):
            view = self.views[family]
            glyph = STATE_GLYPHS[view.state]
            self.bar.setTabText(index, f"{t(FAMILY_TITLES[family])}  {glyph}")
            self.bar.setTabToolTip(
                index,
                f"{t(FAMILY_TITLES[family])} — {t(STATE_LABELS[view.state])}",
            )

    def retranslate(self) -> None:
        for view in self.views.values():
            view.retranslate()
        self.refresh_states()


def family_for_local_kind(kind: str) -> str:
    return {"pairs": PAIRS, "branches": BRANCHES, "future": FUTURE}.get(kind, PAIRS)


def family_for_online_mode(mode: str) -> str:
    return ONLINE_PARENT if mode == "parent" else ONLINE_GP


def local_kind_for_family(family: str) -> str:
    return {PAIRS: "pairs", BRANCHES: "branches", FUTURE: "future"}[family]


def online_mode_for_family(family: str) -> str:
    return "parent" if family == ONLINE_PARENT else "grandparent"


def run_callable(
    family: str,
    start_local: Callable[[str], None],
    start_online: Callable[..., None],
) -> Callable[[], None]:
    if family in LOCAL_FAMILIES:
        kind = local_kind_for_family(family)
        return lambda: start_local(kind)
    mode = online_mode_for_family(family)
    return lambda: start_online(mode)

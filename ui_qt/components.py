from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QScrollArea,
    QSplitter,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui_qt.theme import COLORS


class NoWheelFilter(QObject):
    """Blocks accidental value changes from mouse-wheel scrolling.

    ``QComboBox`` and every spin box respond to wheel events even without
    focus, so scrolling a long page silently changes whatever dropdown or
    number field the cursor happens to pass over. Install one instance on
    ``QApplication`` (see :func:`install_no_wheel_filter`) instead of
    touching every combo/spin box across the project: this intercepts wheel
    events for both widget families unconditionally, and forwards the
    scroll to the nearest scrollable ancestor so the page keeps scrolling
    normally instead of the value changing.

    Focus alone cannot gate this: Qt keeps keyboard focus on a combo or spin
    box after it is clicked, even once the cursor has moved elsewhere, so a
    focus-based check still lets the wheel change that same widget's value
    the next time the cursor happens to pass back over it while scrolling.
    Blocking unconditionally removes that gap. This does not affect an open
    combo-box dropdown: the popup is a separate widget, not the QComboBox
    itself, so scrolling a long open list is unaffected.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and isinstance(
            watched, (QComboBox, QAbstractSpinBox)
        ):
            parent = watched.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    QApplication.sendEvent(parent.viewport(), event)
                    break
                parent = parent.parentWidget()
            return True
        return super().eventFilter(watched, event)


def install_no_wheel_filter(application: QApplication) -> NoWheelFilter:
    """Install the wheel-scroll guard once for the whole application.

    Keeps a reference alive on ``application`` itself: a filter installed via
    ``installEventFilter`` is only kept alive by Qt's C++ side as long as
    something on the Python side also holds a reference, otherwise it can be
    garbage-collected and silently stop filtering.
    """
    guard = NoWheelFilter(application)
    application.installEventFilter(guard)
    application._no_wheel_filter = guard  # keep a strong Python reference
    return guard


def _apply_combo_popup_palette(view: QAbstractItemView) -> None:
    """Keep detached/native combo popups readable on every Qt platform.

    On Windows, a combo or completer popup can be promoted to a top-level
    native window.  In that case it does not always inherit the application's
    descendant stylesheet, which previously produced white text on the native
    white background for a subset of selectors.
    """

    view.setObjectName("comboPopup")
    palette = view.palette()
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["surface_alt"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#27564f"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["text"]))
    view.setPalette(palette)


class ThemedComboBox(QComboBox):
    """QComboBox with a platform-independent dark popup palette."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _apply_combo_popup_palette(self.view())

    def showPopup(self) -> None:
        # Some platform styles rebuild/repolish the popup just before display.
        _apply_combo_popup_palette(self.view())
        super().showPopup()


class SearchableComboBox(ThemedComboBox):
    """Editable combo box whose displayed text and selected data stay in sync.

    Qt normally keeps the previous ``currentIndex`` while the user types in an
    editable combo.  That makes a form look as if a new item was selected while
    ``currentData()`` still returns the old one.  This component invalidates the
    stale index, accepts contains-based completions and resolves an exact or
    unique partial match before the value is consumed.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(14)
        if self.lineEdit() is not None:
            self.lineEdit().setClearButtonEnabled(True)
            self.lineEdit().textEdited.connect(self._text_edited)
            self.lineEdit().editingFinished.connect(self.resolve_current_text)

        completer = self.completer()
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setMaxVisibleItems(16)
        completer.activated[str].connect(self._completion_activated)
        _apply_combo_popup_palette(completer.popup())

    @staticmethod
    def _normalise(value: str) -> str:
        return " ".join(value.strip().casefold().split())

    def _matching_indexes(self, text: str) -> tuple[list[int], list[int]]:
        query = self._normalise(text)
        exact: list[int] = []
        partial: list[int] = []
        for index in range(self.count()):
            candidate = self._normalise(self.itemText(index))
            if candidate == query:
                exact.append(index)
            elif query and query in candidate:
                partial.append(index)
        return exact, partial

    def _text_edited(self, text: str) -> None:
        index = self.currentIndex()
        if index >= 0 and self._normalise(text) != self._normalise(self.itemText(index)):
            # Preserve what was typed while invalidating stale item data.
            self.setCurrentIndex(-1)
            if self.lineEdit() is not None and self.lineEdit().text() != text:
                self.lineEdit().setText(text)
        completer = self.completer()
        completer.setCompletionPrefix(text)
        if text.strip() and self.isVisible():
            _apply_combo_popup_palette(completer.popup())
            completer.complete()

    def _completion_activated(self, text: str) -> None:
        exact, _partial = self._matching_indexes(text)
        if exact:
            self.setCurrentIndex(exact[0])

    def resolve_current_text(self) -> bool:
        """Resolve typed text to an item and return whether it is valid."""

        if self.lineEdit() is None:
            return self.currentIndex() >= 0
        text = self.lineEdit().text()
        exact, partial = self._matching_indexes(text)
        match = exact[0] if exact else (partial[0] if len(partial) == 1 else -1)
        if match >= 0:
            self.setCurrentIndex(match)
            return True
        self.setCurrentIndex(-1)
        self.lineEdit().setText(text)
        return False


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("pageSubtitle")
        self.subtitle_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.subtitle_label)

    def set_text(self, title: str, subtitle: str) -> None:
        self.title_label.setText(title)
        self.subtitle_label.setText(subtitle)


class StatusCard(QFrame):
    def __init__(self, title: str, value: str, detail: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("muted")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metric")
        self.value_label.setWordWrap(True)
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("cardDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
        layout.addStretch(1)

    def set_content(self, title: str, value: str, detail: str, state: str = "neutral") -> None:
        self.title_label.setText(title)
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        color = {
            "ok": "#68d3b1",
            "warning": "#f2c166",
            "error": "#ff7b88",
            "info": "#70a8ff",
            "neutral": "#edf4ff",
        }.get(state, "#edf4ff")
        self.value_label.setStyleSheet(f"color: {color};")


class PathPicker(QWidget):
    path_changed = Signal(str)

    def __init__(
        self,
        value: str = "",
        *,
        mode: str = "file",
        title: str = "",
        file_filter: str = "Tous les fichiers (*)",
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.dialog_title = title
        self.file_filter = file_filter
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.edit = QLineEdit(value)
        self.button = QPushButton("Parcourir…")
        self.button.setFixedWidth(112)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self.browse)
        self.edit.editingFinished.connect(lambda: self.path_changed.emit(self.text()))

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        if self.edit.text() != value:
            self.edit.setText(value)

    def set_button_text(self, text: str) -> None:
        self.button.setText(text)

    def browse(self) -> None:
        current = Path(self.text()).expanduser() if self.text() else Path.home()
        start = current if current.is_dir() else current.parent
        selected = ""
        if self.mode == "directory":
            selected = QFileDialog.getExistingDirectory(self, self.dialog_title, str(start))
        elif self.mode == "save":
            selected, _ = QFileDialog.getSaveFileName(
                self, self.dialog_title, str(current), self.file_filter
            )
        else:
            selected, _ = QFileDialog.getOpenFileName(
                self, self.dialog_title, str(start), self.file_filter
            )
        if selected:
            self.edit.setText(selected)
            self.path_changed.emit(selected)


class CollapsibleSection(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setStyleSheet("QToolButton { border:none; font-weight:650; padding:4px; }")
        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_layout.setSpacing(6)
        self.header_layout.addWidget(self.toggle)
        self.header_layout.addStretch(1)
        self.content = QWidget()
        self.content.setVisible(False)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 2, 4, 2)
        layout.addLayout(self.header_layout)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)

    def set_title(self, title: str) -> None:
        self.toggle.setText(title)


class SummarySection(CollapsibleSection):
    """Collapsible section whose header keeps stating its effective value.

    Collapsing trades content visibility for space, so a plain accordion turns
    every closed panel into state the user has to reopen to recall. That cost
    is unacceptable for settings that change a calculation: a non-default
    condition hidden inside a closed section is indistinguishable from an
    unset one.

    This section therefore hides the *controls*, never the *state*. The header
    keeps a plain-language summary of the effective values, an explicit
    modified marker when they differ from the defaults, and the reset action
    beside them, so a collapsed rail still answers "what will this calculation
    actually use?" at a glance. It reuses the modified/reset vocabulary
    already established by the scoring editor.
    """

    reset_requested = Signal()

    def __init__(self, title: str, parent=None, *, resettable: bool = False):
        super().__init__(title, parent)
        self.modified = QLabel("")
        self.modified.setObjectName("pillAccent")
        self.modified.setVisible(False)
        self.reset_button = QToolButton()
        self.reset_button.setAutoRaise(True)
        self.reset_button.setVisible(resettable)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.header_layout.insertWidget(1, self.modified)
        self.header_layout.addWidget(self.reset_button)

        # The summary sits on its own row rather than beside the title: a
        # narrow rail would otherwise elide exactly the values this section
        # exists to keep readable.
        self.summary = QLabel("")
        self.summary.setObjectName("settingSummary")
        self.summary.setWordWrap(True)
        layout = self.layout()
        layout.insertWidget(1, self.summary)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def set_modified(self, modified: bool, label: str = "") -> None:
        self.modified.setText(label)
        self.modified.setVisible(bool(modified and label))

    def set_reset_text(self, text: str, tooltip: str = "") -> None:
        self.reset_button.setText(text)
        self.reset_button.setToolTip(tooltip or text)


def section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    label.setWordWrap(True)
    return label


def muted_label(text: str, *, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(wrap)
    return label


def sync_scroll_pane_height(
    splitter: QSplitter | None,
    scroll: QScrollArea | None,
    *,
    reserve: int = 96,
) -> None:
    """Keep a form pane in a vertical splitter sized to its real content.

    Two failure modes this guards against:

    * Without a trailing stretch in the scrolled layout, ``setWidgetResizable``
      hands surplus height to the panels, which spread their grid rows apart
      as soon as a collapsible section closes. Callers must add that stretch;
      this helper then measures ``layout().minimumSize()`` rather than
      ``sizeHint()``, which the stretch would inflate.
    * A fixed pixel split drifts out of sync with the actual layout (language,
      DPI, populated fields, collapsed sections). The maximum is enforced on
      the scroll area itself, not just picked as an initial split, because Qt
      honours it while the user drags the handle.

    ``reserve`` is the strip left to the pane below by default. It stays small
    on purpose: the form is the part worth showing in full, and the handle can
    always be dragged back up.
    """
    if splitter is None or scroll is None:
        return
    widget = scroll.widget()
    layout = widget.layout() if widget is not None else None
    if layout is None:
        return
    total = sum(splitter.sizes()) or splitter.height()
    if total <= 0:
        return
    content_height = layout.minimumSize().height() + 4
    top = max(160, min(content_height, total - reserve))
    scroll.setMaximumHeight(min(content_height, max(top, total - 60)))
    scroll.setMinimumHeight(min(content_height, 140))
    splitter.setSizes([top, max(60, total - top)])

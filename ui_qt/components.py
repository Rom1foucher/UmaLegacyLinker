from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
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


class SearchableComboBox(QComboBox):
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
        self.button.setFixedWidth(104)
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
        self.content = QWidget()
        self.content.setVisible(False)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self.toggle)
        layout.addWidget(self.content)
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)

    def set_title(self, title: str) -> None:
        self.toggle.setText(title)


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

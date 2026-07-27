from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThreadPool, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import LANGUAGE_LABELS
from ui_qt.components import ThemedComboBox
from ui_qt.context import AppContext
from ui_qt.core import APP_NAME, APP_VERSION
from ui_qt.pages_home_data import DataPage, HomePage
from ui_qt.pages_online import OnlinePage
from ui_qt.pages_optimizer import OptimizerPage
from ui_qt.pages_tools import ToolsPage
from ui_qt.pages_transfer import TransferPage
from ui_qt.pages_weights import WeightsPage
from ui_qt.workers import FunctionWorker


class MainWindow(QMainWindow):
    def __init__(self, context: AppContext | None = None):
        super().__init__()
        self.context = context or AppContext()
        self.thread_pool = QThreadPool.globalInstance()
        self._workers: list[FunctionWorker] = []
        self._active_worker: FunctionWorker | None = None
        self._busy = False
        self._status_source = "Prêt"
        self._nav_order = ["home", "data", "optimizer", "online", "transfer", "weights", "tools"]
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_sections: dict[str, QLabel] = {}
        self._pages: dict[str, QWidget] = {}

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1460, 940)
        self.setMinimumSize(1120, 720)

        central = QWidget()
        central.setObjectName("root")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(252)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 15, 16, 13)
        sidebar_layout.setSpacing(4)

        brand = QLabel("Uma Legacy\nLinker")
        brand.setObjectName("brand")
        sidebar_layout.addWidget(brand)
        badges = QHBoxLayout()
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("versionBadge")
        badges.addWidget(version)
        badges.addStretch(1)
        sidebar_layout.addLayout(badges)
        sidebar_layout.addSpacing(9)

        nav_group = QButtonGroup(self)
        nav_group.setExclusive(True)
        nav_sections = (
            ("overview", ("home",)),
            ("prepare", ("data",)),
            ("analyse", ("optimizer", "online", "transfer")),
            ("configure", ("weights", "tools")),
        )
        for section_key, page_keys in nav_sections:
            label = QLabel("")
            label.setObjectName("navSection")
            self._nav_sections[section_key] = label
            sidebar_layout.addWidget(label)
            for key in page_keys:
                button = QPushButton()
                button.setObjectName("nav")
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, target=key: self.show_page(target))
                nav_group.addButton(button)
                self._nav_buttons[key] = button
                sidebar_layout.addWidget(button)
            sidebar_layout.addSpacing(2)
        sidebar_layout.addStretch(1)

        self.language_label = QLabel("")
        self.language_label.setObjectName("muted")
        self.language_combo = ThemedComboBox()
        for code, label in LANGUAGE_LABELS.items():
            self.language_combo.addItem(label, code)
        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(self.context.language))
        )
        self.language_combo.currentIndexChanged.connect(self._language_selected)
        sidebar_layout.addWidget(self.language_label)
        sidebar_layout.addWidget(self.language_combo)
        outer.addWidget(sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)

        self.log_frame = QFrame()
        self.log_frame.setObjectName("panel")
        self.log_frame.setMaximumHeight(280)
        self.log_frame.setVisible(False)
        log_layout = QVBoxLayout(self.log_frame)
        log_layout.setContentsMargins(16, 9, 16, 12)
        log_head = QHBoxLayout()
        self.log_title = QLabel("")
        self.log_title.setObjectName("sectionTitle")
        self.clear_log_button = QPushButton("")
        self.clear_log_button.clicked.connect(lambda: self.log.clear())
        log_head.addWidget(self.log_title)
        log_head.addStretch(1)
        log_head.addWidget(self.clear_log_button)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        log_layout.addLayout(log_head)
        log_layout.addWidget(self.log)
        right_layout.addWidget(self.log_frame)

        status = QFrame()
        status.setObjectName("sidebar")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(14, 7, 14, 7)
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        self.progress.setVisible(False)
        self.log_button = QPushButton("")
        self.log_button.setCheckable(True)
        self.log_button.toggled.connect(self.log_frame.setVisible)
        self.cancel_button = QPushButton("")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._request_cancel)
        status_layout.addWidget(self.status_label, 1)
        status_layout.addWidget(self.progress)
        status_layout.addWidget(self.cancel_button)
        status_layout.addWidget(self.log_button)
        right_layout.addWidget(status)
        outer.addWidget(right, 1)

        home = HomePage(self.context)
        data = DataPage(self.context)
        optimizer = OptimizerPage(self.context)
        online = OnlinePage(self.context)
        transfer = TransferPage(self.context)
        weights = WeightsPage(self.context)
        tools_page = ToolsPage(self.context)
        self._pages = {
            "home": home,
            "data": data,
            "optimizer": optimizer,
            "online": online,
            "transfer": transfer,
            "weights": weights,
            "tools": tools_page,
        }
        for key in self._nav_order:
            self.stack.addWidget(self._pages[key])

        home.navigate_requested.connect(self.show_page)
        data.task_requested.connect(self.start_task)
        optimizer.task_requested.connect(self.start_task)
        online.task_requested.connect(self.start_task)
        transfer.task_requested.connect(self.start_task)
        tools_page.task_requested.connect(self.start_task)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self.retranslate()
        self.show_page("home")

    def retranslate(self) -> None:
        t = self.context.t
        self.cancel_button.setText(t("Annuler la tâche"))
        labels = {
            "home": "Accueil",
            "data": "Données locales",
            "optimizer": "Optimisation de lignée",
            "online": "Recherche uma.moe",
            "transfer": "Transfer Helper",
            "weights": "Pondérations",
            "tools": "Outils et diagnostics",
        }
        prefixes = {
            "home": "⌂",
            "data": "◫",
            "optimizer": "◇",
            "online": "⌕",
            "transfer": "⇄",
            "weights": "⚙",
            "tools": "⌘",
        }
        for key, source in labels.items():
            self._nav_buttons[key].setText(f"{prefixes[key]}   {t(source)}")
        section_labels = {
            "overview": "VUE D’ENSEMBLE",
            "prepare": "PRÉPARER",
            "analyse": "ANALYSER",
            "configure": "CONFIGURER",
        }
        for key, source in section_labels.items():
            self._nav_sections[key].setText(t(source))
        self.language_label.setText(t("Langue"))
        self.log_title.setText(t("Journal d’exécution"))
        self.clear_log_button.setText(t("Effacer"))
        self.log_button.setText(t("Journal"))
        self.status_label.setText(t(self._status_source))

    @Slot(int)
    def _language_selected(self, _index: int) -> None:
        code = str(self.language_combo.currentData() or "fr")
        self.context.set_language(code)

    @Slot(str)
    def show_page(self, key: str) -> None:
        if key not in self._pages:
            return
        self.stack.setCurrentWidget(self._pages[key])
        self._nav_buttons[key].setChecked(True)

    def append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{timestamp}] {self.context.t(message)}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_status(self, source: str) -> None:
        self._status_source = source
        self.status_label.setText(self.context.t(source))

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for page in self._pages.values():
            setter = getattr(page, "set_busy", None)
            if callable(setter):
                setter(busy)
        self.language_combo.setEnabled(not busy)
        self.progress.setVisible(busy)
        if not busy:
            self.progress.setValue(0)

    @Slot(object, str, object)
    def start_task(
        self,
        operation: Callable[..., Any],
        title: str,
        on_success: Callable[[object], None],
    ) -> None:
        if self._busy:
            QMessageBox.information(
                self,
                self.context.t("Opération en cours"),
                self.context.t("Attends la fin du calcul actuel avant d’en lancer un autre."),
            )
            return
        self._set_busy(True)
        self._status_source = title
        self.status_label.setText(title)
        self.progress.setValue(1)
        self.append_log(title)

        worker = FunctionWorker(operation)
        self._workers.append(worker)
        self._active_worker = worker
        self.cancel_button.setEnabled(True)
        worker.signals.progress.connect(self._task_progress)
        worker.signals.log.connect(self.append_log)
        worker.signals.result.connect(lambda result: self._task_result(on_success, result))
        worker.signals.error.connect(self._task_error)
        worker.signals.cancelled.connect(self._task_cancelled)
        worker.signals.finished.connect(lambda: self._task_finished(worker))
        self.thread_pool.start(worker)

    def _request_cancel(self) -> None:
        worker = self._active_worker
        if worker is None:
            return
        worker.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self._status_source = "Annulation demandée — arrêt à la prochaine étape…"
        self.status_label.setText(self.context.t(self._status_source))
        self.append_log(self.context.t(self._status_source))

    @Slot()
    def _task_cancelled(self) -> None:
        self._status_source = "Tâche annulée."
        self.append_log(self.context.t(self._status_source))

    @Slot(int, str)
    def _task_progress(self, value: int, message: str) -> None:
        self.progress.setValue(max(0, min(100, value)))
        self._status_source = message
        self.status_label.setText(self.context.t(message))

    def _task_result(self, callback: Callable[[object], None], result: object) -> None:
        try:
            callback(result)
        except Exception as exc:
            self.append_log(f"Erreur d’affichage : {exc}")
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))

    @Slot(str, str)
    def _task_error(self, message: str, trace: str) -> None:
        self.append_log(message)
        self.log.appendPlainText(trace)
        self.log_button.setChecked(True)
        QMessageBox.critical(
            self,
            self.context.t("L’opération a échoué"),
            self.context.t(message),
        )

    def _task_finished(self, worker: FunctionWorker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if worker is self._active_worker:
            self._active_worker = None
        self.cancel_button.setEnabled(False)
        self._set_busy(False)
        self.set_status("Prêt")
        for page in self._pages.values():
            refresher = getattr(page, "refresh", None)
            if callable(refresher) and page is self._pages.get("home"):
                refresher()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._busy:
            self._pages["online"].persist_api_key()
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            self.context.t("Calcul en cours"),
            self.context.t("Un calcul est encore en cours. Fermer l’application maintenant ?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pages["online"].persist_api_key()
            event.accept()
        else:
            event.ignore()

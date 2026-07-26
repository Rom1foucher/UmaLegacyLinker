from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui_qt.components import PageHeader, PathPicker, StatusCard, muted_label, section_label
from ui_qt.context import AppContext
from ui_qt.core import (
    CatalogRequest,
    ExtractRequest,
    LinkRequest,
    collection_size,
    latest_rankings_path,
    linked_veterans_path,
    open_path,
    run_catalog,
    run_extract_and_link,
    run_link,
)


class HomePage(QWidget):
    navigate_requested = Signal(str)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        self.header = PageHeader("", "")
        root.addWidget(self.header)

        cards = QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        self.master_card = StatusCard("", "", "")
        self.collection_card = StatusCard("", "", "")
        self.results_card = StatusCard("", "", "")
        cards.addWidget(self.master_card, 0, 0)
        cards.addWidget(self.collection_card, 0, 1)
        cards.addWidget(self.results_card, 0, 2)
        cards.setColumnStretch(0, 1)
        cards.setColumnStretch(1, 1)
        cards.setColumnStretch(2, 1)
        root.addLayout(cards)

        action_panel = QFrame()
        action_panel.setObjectName("panel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(18, 16, 18, 16)
        action_layout.setSpacing(10)
        self.quick_title = section_label("")
        self.quick_detail = muted_label("")
        buttons = QHBoxLayout()
        self.data_button = QPushButton("")
        self.data_button.setObjectName("primary")
        self.optimizer_button = QPushButton("")
        self.online_button = QPushButton("")
        self.transfer_button = QPushButton("")
        self.refresh_button = QPushButton("")
        buttons.addWidget(self.data_button)
        buttons.addWidget(self.optimizer_button)
        buttons.addWidget(self.online_button)
        buttons.addWidget(self.transfer_button)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_button)
        action_layout.addWidget(self.quick_title)
        action_layout.addWidget(self.quick_detail)
        action_layout.addLayout(buttons)
        root.addWidget(action_panel)

        preview_panel = QFrame()
        preview_panel.setObjectName("panel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(18, 16, 18, 16)
        self.preview_title = section_label("")
        self.preview_text = muted_label("")
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_text)
        root.addWidget(preview_panel)
        root.addStretch(1)

        self.data_button.clicked.connect(lambda: self.navigate_requested.emit("data"))
        self.optimizer_button.clicked.connect(lambda: self.navigate_requested.emit("optimizer"))
        self.online_button.clicked.connect(lambda: self.navigate_requested.emit("online"))
        self.transfer_button.clicked.connect(lambda: self.navigate_requested.emit("transfer"))
        self.refresh_button.clicked.connect(self.refresh)
        self.context.configuration_changed.connect(self._schedule_refresh)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh)
        self.retranslate()
        self.refresh()

    def _schedule_refresh(self) -> None:
        self._refresh_timer.start(120)

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Vue d’ensemble"),
            t("Prépare les données, lance un calcul et retrouve immédiatement le dernier état utile."),
        )
        self.quick_title.setText(t("Actions rapides"))
        self.quick_detail.setText(
            t("Prépare ta collection, optimise une lignée ou lance directement une analyse ciblée.")
        )
        self.data_button.setText(t("Configurer les données"))
        self.optimizer_button.setText(t("Nouvelle optimisation"))
        self.online_button.setText(t("Recherche uma.moe"))
        self.transfer_button.setText(t("Transfer Helper"))
        self.refresh_button.setText(t("Actualiser"))
        self.preview_title.setText(t("Interface Qt complète"))
        self.preview_text.setText(
            t("Tous les workflows principaux utilisent désormais les mêmes moteurs dans l’interface Qt : extraction, optimisation, recherche uma.moe, Transfer Helper, pondérations et outils de diagnostic.")
        )
        self.refresh()

    def refresh(self) -> None:
        t = self.context.t
        master = Path(self.context.master_path).expanduser()
        if master.is_file():
            self.master_card.set_content(
                t("Base du jeu"), t("Détectée"), master.name, "ok"
            )
        else:
            self.master_card.set_content(
                t("Base du jeu"), t("À configurer"), t("master.mdb est requis"), "warning"
            )

        data_path = Path(self.context.veterans_json_path).expanduser()
        count = collection_size(data_path) if data_path.is_file() else None
        if count is not None:
            self.collection_card.set_content(
                t("Collection locale"),
                t("{count} vétérans").replace("{count}", str(count)),
                data_path.name,
                "ok",
            )
        elif data_path.is_file():
            self.collection_card.set_content(
                t("Collection locale"), t("JSON invalide"), data_path.name, "error"
            )
        else:
            self.collection_card.set_content(
                t("Collection locale"), t("À sélectionner"), t("data.json est requis"), "warning"
            )

        rankings = latest_rankings_path(self.context.output_dir)
        output = Path(self.context.output_dir).expanduser()
        result_candidates = [
            path for path in (
                rankings,
                output / "uma_moe_parent_pairs.json",
                output / "uma_moe_grandparent_pairs.json",
                output / "transfer_helper_report.json",
            )
            if path.is_file()
        ]
        linked = linked_veterans_path(self.context.output_dir)
        if result_candidates:
            latest = max(result_candidates, key=lambda path: path.stat().st_mtime)
            self.results_card.set_content(
                t("Dernier calcul"), t("Disponible"), latest.name, "ok"
            )
        elif linked.is_file():
            self.results_card.set_content(
                t("Dernier calcul"), t("Données liées"), t("Prêt pour une optimisation"), "neutral"
            )
        else:
            self.results_card.set_content(
                t("Dernier calcul"), t("Aucun"), t("Commence par préparer les données"), "neutral"
            )


class DataPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self._busy = False
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        self.header = PageHeader("", "")
        root.addWidget(self.header)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 17, 18, 17)
        panel_layout.setSpacing(11)
        self.files_title = section_label("")
        panel_layout.addWidget(self.files_title)

        self.master_label = QLabel("")
        self.master_picker = PathPicker(
            self.context.master_path,
            title="Sélectionner master.mdb",
            file_filter="master.mdb (*.mdb);;Tous les fichiers (*)",
        )
        self.data_label = QLabel("")
        self.data_picker = PathPicker(
            self.context.veterans_json_path,
            title="Sélectionner data.json",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.extractor_label = QLabel("")
        self.extractor_picker = PathPicker(
            self.context.extractor_path,
            title="Sélectionner UmaExtractor ou umadump",
            file_filter="Extracteur (*.exe *.py);;Tous les fichiers (*)",
        )
        self.output_label = QLabel("")
        self.output_picker = PathPicker(
            self.context.output_dir,
            mode="directory",
            title="Sélectionner le dossier de sortie",
        )
        sources = QGridLayout()
        sources.setHorizontalSpacing(14)
        sources.setVerticalSpacing(7)
        for index, (label, picker) in enumerate(
            (
                (self.master_label, self.master_picker),
                (self.data_label, self.data_picker),
                (self.extractor_label, self.extractor_picker),
                (self.output_label, self.output_picker),
            )
        ):
            row = (index // 2) * 2
            column = index % 2
            sources.addWidget(label, row, column)
            sources.addWidget(picker, row + 1, column)
            sources.setColumnStretch(column, 1)
        panel_layout.addLayout(sources)

        actions = QHBoxLayout()
        self.link_button = QPushButton("")
        self.link_button.setObjectName("primary")
        self.extract_button = QPushButton("")
        self.catalog_button = QPushButton("")
        self.open_button = QPushButton("")
        actions.addWidget(self.link_button)
        actions.addWidget(self.extract_button)
        actions.addWidget(self.catalog_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        panel_layout.addLayout(actions)
        resources = QHBoxLayout()
        self.extractor_download = QPushButton("")
        self.umadump_link = QPushButton("")
        resources.addWidget(self.extractor_download)
        resources.addWidget(self.umadump_link)
        resources.addStretch(1)
        panel_layout.addLayout(resources)
        root.addWidget(panel)

        self.result_card = StatusCard("", "", "")
        root.addWidget(self.result_card)
        self.help_text = muted_label("")
        root.addWidget(self.help_text)
        root.addStretch(1)

        self.master_picker.path_changed.connect(
            lambda value: self.context.update_paths(master_path=value)
        )
        self.data_picker.path_changed.connect(
            lambda value: self.context.update_paths(veterans_json_path=value)
        )
        self.output_picker.path_changed.connect(
            lambda value: self.context.update_paths(output_dir=value)
        )
        self.extractor_picker.path_changed.connect(
            lambda value: self.context.update_paths(extractor_path=value)
        )
        self.link_button.clicked.connect(self.start_link)
        self.extract_button.clicked.connect(self.start_extract)
        self.catalog_button.clicked.connect(self.start_catalog)
        self.open_button.clicked.connect(self.open_output)
        self.extractor_download.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/xancia/UmaExtractor/releases/latest"))
        )
        self.umadump_link.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/Werseter/umadump"))
        )
        self.context.configuration_changed.connect(self.sync_from_context)
        self.context.language_changed.connect(lambda _language: self.retranslate())
        self.retranslate()
        self.refresh_status()

    def sync_from_context(self) -> None:
        self.master_picker.set_text(self.context.master_path)
        self.data_picker.set_text(self.context.veterans_json_path)
        self.extractor_picker.set_text(self.context.extractor_path)
        self.output_picker.set_text(self.context.output_dir)
        self.refresh_status()

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Données locales"),
            t("Relie ton export de vétérans au master.mdb courant avant les analyses."),
        )
        self.files_title.setText(t("Sources et sortie"))
        self.master_label.setText(t("Base actuelle du jeu — master.mdb"))
        self.data_label.setText(t("Collection exportée — data.json"))
        self.extractor_label.setText(t("Extracteur — UmaExtractor ou umadump, optionnel pour créer le JSON"))
        self.output_label.setText(t("Dossier de sortie"))
        self.master_picker.dialog_title = t("Sélectionner master.mdb")
        self.master_picker.file_filter = f"master.mdb (*.mdb);;{t('Tous les fichiers')} (*)"
        self.data_picker.dialog_title = t("Sélectionner data.json")
        self.data_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.extractor_picker.dialog_title = t("Sélectionner UmaExtractor ou umadump")
        self.extractor_picker.file_filter = f"{t('Extracteur')} (*.exe *.py);;{t('Tous les fichiers')} (*)"
        self.output_picker.dialog_title = t("Sélectionner le dossier de sortie")
        for picker in (self.master_picker, self.data_picker, self.extractor_picker, self.output_picker):
            picker.set_button_text(t("Parcourir…"))
        self.link_button.setText(t("Lier la collection"))
        self.extract_button.setText(t("Extraire puis lier"))
        self.catalog_button.setText(t("Générer les catalogues"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.extractor_download.setText(t("Télécharger UmaExtractor"))
        self.umadump_link.setText(t("Télécharger umadump"))
        self.help_text.setText(
            t("Cette opération reconstruit les Sparks, skills, G1 et lignées sans modifier ton export original.")
        )
        self.refresh_status()

    def refresh_status(self) -> None:
        t = self.context.t
        output = Path(self.context.output_dir).expanduser()
        linked = linked_veterans_path(output)
        if linked.is_file():
            self.result_card.set_content(
                t("État de la liaison"), t("Prête"), str(linked), "ok"
            )
        else:
            self.result_card.set_content(
                t("État de la liaison"),
                t("Pas encore générée"),
                t("Le fichier enrichi apparaîtra ici après la liaison."),
                "neutral",
            )

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.link_button.setEnabled(not busy)
        self.extract_button.setEnabled(not busy)
        self.catalog_button.setEnabled(not busy)

    def start_link(self) -> None:
        self.context.update_paths(
            master_path=self.master_picker.text(),
            veterans_json_path=self.data_picker.text(),
            output_dir=self.output_picker.text(),
        )
        request = LinkRequest(
            Path(self.context.master_path).expanduser(),
            Path(self.context.veterans_json_path).expanduser(),
            Path(self.context.output_dir).expanduser(),
        )
        operation = partial(run_link, request)
        self.task_requested.emit(operation, self.context.t("Liaison de la collection…"), self._link_done)

    def _link_done(self, result: object) -> None:
        self.refresh_status()
        veteran_count = getattr(result, "veteran_count", 0)
        self.result_card.set_content(
            self.context.t("État de la liaison"),
            self.context.t("Terminée"),
            self.context.t("{count} vétérans enrichis").replace("{count}", str(veteran_count)),
            "ok",
        )

    def start_extract(self) -> None:
        self.context.update_paths(
            master_path=self.master_picker.text(),
            output_dir=self.output_picker.text(),
            extractor_path=self.extractor_picker.text(),
        )
        request = ExtractRequest(
            Path(self.context.extractor_path).expanduser(),
            Path(self.context.master_path).expanduser(),
            Path(self.context.output_dir).expanduser(),
        )
        self.task_requested.emit(
            partial(run_extract_and_link, request),
            self.context.t("Extraction et liaison…"),
            self._extract_done,
        )

    def _extract_done(self, result: object) -> None:
        data_path = Path(getattr(result, "data_json_path"))
        self.context.update_paths(veterans_json_path=str(data_path))
        self.data_picker.set_text(str(data_path))
        linked = getattr(result, "link_result", None)
        self._link_done(linked)

    def start_catalog(self) -> None:
        self.context.update_paths(
            master_path=self.master_picker.text(), output_dir=self.output_picker.text()
        )
        request = CatalogRequest(
            Path(self.context.master_path).expanduser(),
            Path(self.context.output_dir).expanduser(),
        )
        self.task_requested.emit(
            partial(run_catalog, request),
            self.context.t("Génération des catalogues…"),
            self._catalog_done,
        )

    def _catalog_done(self, result: object) -> None:
        count = getattr(result, "skill_count", 0)
        self.result_card.set_content(
            self.context.t("Catalogues skills"),
            self.context.t("Terminés"),
            self.context.t("{count} skills indexées").replace("{count}", str(count)),
            "ok",
        )

    def open_output(self) -> None:
        output = Path(self.output_picker.text()).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))

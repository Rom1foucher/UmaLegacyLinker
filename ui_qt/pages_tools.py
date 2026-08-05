from __future__ import annotations

import os
from functools import partial
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QCheckBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from secret_store import SecretStoreError
from ui_qt.components import PageHeader, PathPicker, StatusCard, muted_label, section_label
from ui_qt.context import AppContext
from ui_qt.core import SimulatorImportRequest, open_path, run_simulator_import


class ToolsPage(QWidget):
    task_requested = Signal(object, str, object)

    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(14)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        self.integration_panel = QFrame()
        self.integration_panel.setObjectName("panel")
        integration = QGridLayout(self.integration_panel)
        integration.setContentsMargins(18, 16, 18, 16)
        integration.setHorizontalSpacing(12)
        integration.setVerticalSpacing(8)
        self.integration_title = section_label("")
        self.integration_hint = muted_label("")
        self.api_base_label = QLabel("")
        self.api_base = QLineEdit(context.uma_moe_api_base)
        self.api_key_label = QLabel("")
        self.api_key = QLineEdit(context.uma_moe_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = QPushButton("")
        self.remember_key = QCheckBox("")
        self.remember_key.setChecked(context.uma_moe_remember_api_key)
        self.save_integration_button = QPushButton("")
        self.save_integration_button.setObjectName("primary")
        self.integration_status = muted_label("")
        integration.addWidget(self.integration_title, 0, 0, 1, 3)
        integration.addWidget(self.integration_hint, 1, 0, 1, 3)
        integration.addWidget(self.api_base_label, 2, 0)
        integration.addWidget(self.api_base, 3, 0, 1, 3)
        integration.addWidget(self.api_key_label, 4, 0)
        integration.addWidget(self.api_key, 5, 0, 1, 2)
        integration.addWidget(self.show_key, 5, 2)
        integration.addWidget(self.remember_key, 6, 0, 1, 2)
        integration.addWidget(self.save_integration_button, 6, 2)
        integration.addWidget(self.integration_status, 7, 0, 1, 3)
        integration.setColumnStretch(0, 1)
        integration.setColumnStretch(1, 1)
        root.addWidget(self.integration_panel)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(9)
        self.import_title = section_label("")
        self.import_hint = muted_label("")
        self.batch_label = QLabel("")
        self.batch_picker = PathPicker(
            context.store.get("batch_path"),
            title="Sélectionner le batch Umalator v2",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.course_label = QLabel("")
        self.course_picker = PathPicker(
            context.course_overrides_path,
            title="Sélectionner les overrides de course",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        actions = QHBoxLayout()
        self.import_button = QPushButton("")
        self.import_button.setObjectName("primary")
        self.open_button = QPushButton("")
        actions.addWidget(self.import_button)
        actions.addWidget(self.open_button)
        actions.addStretch(1)
        panel_layout.addWidget(self.import_title)
        panel_layout.addWidget(self.import_hint)
        panel_layout.addWidget(self.batch_label)
        panel_layout.addWidget(self.batch_picker)
        panel_layout.addWidget(self.course_label)
        panel_layout.addWidget(self.course_picker)
        panel_layout.addLayout(actions)
        root.addWidget(panel)

        cards = QGridLayout()
        self.skills_card = StatusCard("", "—", "")
        self.review_card = StatusCard("", "—", "")
        self.adjustments_card = StatusCard("", "—", "")
        cards.addWidget(self.skills_card, 0, 0)
        cards.addWidget(self.review_card, 0, 1)
        cards.addWidget(self.adjustments_card, 0, 2)
        for column in range(3):
            cards.setColumnStretch(column, 1)
        root.addLayout(cards)

        note = QFrame()
        note.setObjectName("panel")
        note_layout = QVBoxLayout(note)
        note_layout.setContentsMargins(18, 15, 18, 15)
        self.note_title = section_label("")
        self.note_text = muted_label("")
        note_layout.addWidget(self.note_title)
        note_layout.addWidget(self.note_text)
        root.addWidget(note)
        root.addStretch(1)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)

        self.batch_picker.path_changed.connect(
            lambda value: context.store.update({"batch_path": value})
        )
        self.course_picker.path_changed.connect(
            lambda value: context.update_paths(course_overrides_path=value)
        )
        self.import_button.clicked.connect(self.start_import)
        self.open_button.clicked.connect(self.open_output)
        self.show_key.clicked.connect(self._toggle_key)
        self.save_integration_button.clicked.connect(self.save_integration)
        context.integration_changed.connect(self._sync_integration)
        context.language_changed.connect(self._language_changed)
        self.retranslate()

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Paramètres"),
            t("Configure les intégrations stables et retrouve les outils techniques secondaires."),
        )
        self.integration_title.setText(t("Intégration uma.moe"))
        self.integration_hint.setText(
            t("L’URL et la clé sont utilisées par toutes les recherches distantes. Elles ne modifient jamais les pondérations du score.")
        )
        self.api_base_label.setText(t("Base API"))
        self.api_key_label.setText(t("Clé API"))
        hidden = self.api_key.echoMode() == QLineEdit.EchoMode.Password
        self.show_key.setText(t("Afficher" if hidden else "Masquer"))
        if os.name == "nt":
            remember_text = "Mémoriser la clé sur ce PC — chiffrée par Windows"
            remember_tooltip = "La clé mémorisée est chiffrée par Windows pour ce compte utilisateur."
        else:
            remember_text = "Mémoriser la clé sur ce PC — fichier local non chiffré"
            remember_tooltip = (
                "La clé mémorisée est stockée localement dans un fichier lisible uniquement "
                "par ton compte utilisateur ; elle n’est pas chiffrée."
            )
        self.remember_key.setText(t(remember_text))
        self.remember_key.setToolTip(t(remember_tooltip))
        self.save_integration_button.setText(t("Enregistrer l’intégration"))
        self._update_integration_status()
        self.import_title.setText(t("Import Umalator — diagnostic"))
        self.import_hint.setText(
            t("Le classement principal utilise désormais les priorités manuelles intégrées. Cet import reste utile pour comparer ou inspecter d’anciens batchs Skill Chart v2.")
        )
        self.batch_label.setText(t("Batch Umalator v2"))
        self.course_label.setText(t("Presets / overrides de course"))
        self.batch_picker.dialog_title = t("Sélectionner le batch Umalator v2")
        self.course_picker.dialog_title = t("Sélectionner les overrides de course")
        self.batch_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.course_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.batch_picker.set_button_text(t("Parcourir…"))
        self.course_picker.set_button_text(t("Parcourir…"))
        self.import_button.setText(t("Importer les poids Umalator"))
        self.open_button.setText(t("Ouvrir la sortie"))
        self.skills_card.set_content(t("Skills normalisées"), self.skills_card.value_label.text(), t("Valeurs issues du batch"), "neutral")
        self.review_card.set_content(t("À examiner"), self.review_card.value_label.text(), t("Variables dépendantes de la simulation"), "warning")
        self.adjustments_card.set_content(t("Ajustements"), self.adjustments_card.value_label.text(), t("Cellules corrigées manuellement"), "neutral")
        self.note_title.setText(t("À retenir"))
        self.note_text.setText(
            t("Ces fichiers ne remplacent pas automatiquement tes priorités de white skills. Ils sont écrits dans le dossier de sortie pour comparaison et revue.")
        )

    def _toggle_key(self) -> None:
        hidden = self.api_key.echoMode() == QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password
        )
        self.show_key.setText(self.context.t("Masquer" if hidden else "Afficher"))

    def _sync_integration(self) -> None:
        self.api_base.setText(self.context.uma_moe_api_base)
        self.api_key.setText(self.context.uma_moe_api_key)
        self.remember_key.setChecked(self.context.uma_moe_remember_api_key)
        self._update_integration_status()

    def _update_integration_status(self, saved: bool = False) -> None:
        t = self.context.t
        if self.api_key.text().strip():
            status = t("Clé API configurée")
        else:
            status = t("Aucune clé API configurée")
        if saved:
            status = t("Intégration enregistrée") + f" · {status}"
        self.integration_status.setText(status)

    def save_integration(self) -> None:
        try:
            self.context.update_uma_moe_integration(
                api_base=self.api_base.text(),
                api_key=self.api_key.text(),
                remember_api_key=self.remember_key.isChecked(),
            )
        except (OSError, SecretStoreError) as exc:
            QMessageBox.warning(
                self,
                self.context.t("Clé API"),
                self.context.t("La clé n’a pas pu être mémorisée.") + f"\n\n{exc}",
            )
            return
        self._update_integration_status(saved=True)

    def start_import(self) -> None:
        batch = Path(self.batch_picker.text()).expanduser()
        course_text = self.course_picker.text()
        request = SimulatorImportRequest(
            master_path=Path(self.context.master_path).expanduser(),
            batch_path=batch,
            output_dir=Path(self.context.output_dir).expanduser(),
            course_overrides_path=(Path(course_text).expanduser() if course_text else None),
        )
        self.context.store.update({"batch_path": str(batch)})
        self.task_requested.emit(
            partial(run_simulator_import, request),
            self.context.t("Import et normalisation des poids Umalator…"),
            self._import_done,
        )

    def _import_done(self, result: object) -> None:
        self.skills_card.set_content(
            self.context.t("Skills normalisées"),
            str(getattr(result, "skill_count", 0)),
            self.context.t("dont {count} simulées").replace("{count}", str(getattr(result, "simulated_skill_count", 0))),
            "ok",
        )
        self.review_card.set_content(
            self.context.t("À examiner"),
            str(getattr(result, "review_item_count", 0)),
            self.context.t("Variables dépendantes de la simulation"),
            "warning",
        )
        self.adjustments_card.set_content(
            self.context.t("Ajustements"),
            str(getattr(result, "manually_adjusted_cell_count", 0)),
            self.context.t("Cellules corrigées manuellement"),
            "neutral",
        )

    def set_busy(self, busy: bool) -> None:
        self.import_button.setEnabled(not busy)

    def open_output(self) -> None:
        output = Path(self.context.output_dir).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
            open_path(output)
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))

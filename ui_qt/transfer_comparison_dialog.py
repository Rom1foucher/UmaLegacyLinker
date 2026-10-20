from __future__ import annotations

from html import escape
from typing import Any

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QScrollArea, QHBoxLayout, QPushButton, QWidget, QDialog, QDialogButtonBox, QGridLayout, QHeaderView,
    QLabel, QSizePolicy, QTabWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
)

from ui_qt.accessibility import label_control
from ui_qt.components import ThemedComboBox, CollapsibleSection, SummarySection
from ui_qt.table_typography import enable_tabular_numbers
from ui_qt.typography import css_point_size
from uma_legacy_linker.i18n import profile_label
from uma_legacy_linker.transfer_comparison import (
    comparison_evaluation, factor_inventory, white_inventory,
)
from uma_legacy_linker.veteran_identity import (
    game_veteran_label as canonical_veteran_label, game_rank_label, format_rank_score,
)
from ui_qt.image_assets import image_repository
from ui_qt.lineage_view import ZoomControl
from ui_qt.transfer_lineage import TransferLineageTree, comparison_nodes, node_detail_html
from ui_qt.transfer_explanation import comparison_explanation, explanation_html


class TransferComparisonDialog(QDialog):
    """Compare copies against the same Ace, with an additive score explanation."""

    def __init__(self, context, candidate: dict, alternatives: list[dict], model: dict, parent=None):
        super().__init__(parent)
        self.context, self.candidate, self.alternatives, self.model = context, candidate, alternatives, model
        t = context.t
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowTitle(t("Pourquoi cette copie ?"))
        available = self.screen().availableGeometry()
        self.resize(min(1280, int(available.width() * .94)),
                    min(850, int(available.height() * .94)))
        root = QVBoxLayout(self)
        self.identity = QLabel(canonical_veteran_label(candidate))
        self.identity.setWordWrap(True)
        self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setMaximumHeight(48)
        self.identity.setToolTip(canonical_veteran_label(candidate))
        root.addWidget(self.identity)
        self.notice = QLabel(t("Même Ace, même course et même rôle. Les écarts sont calculés avec le modèle enregistré dans ce rapport."))
        if candidate.get("analysis_status", candidate.get("status")) == "recommended_transfer":
            self.notice.setText(self.notice.text() + " " + t("La couverture est collective : plusieurs copies conservées couvrent les niches. Une comparaison individuelle peut montrer un écart négatif."))
        self.notice.setWordWrap(True)
        root.addWidget(self.notice)
        controls = QGridLayout()
        self.target = ThemedComboBox()
        self.role = ThemedComboBox()
        self.course = ThemedComboBox()
        self.ace = ThemedComboBox()
        for column, (text, widget) in enumerate((
            ("Copie comparée", self.target), ("Rôle", self.role),
            ("Contexte", self.course), ("Ace cible", self.ace),
        )):
            label = QLabel(t(text))
            label_control(label, widget)
            controls.addWidget(label, 0, column)
            controls.addWidget(widget, 1, column)
            widget.setSizeAdjustPolicy(ThemedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            widget.setMinimumContentsLength(12 if column == 1 else 18)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            controls.setColumnStretch(column, (3, 1, 2, 2)[column])
        for i, record in enumerate(alternatives):
            suffix = " · " + t("Protégé") if record.get("manual_protection_reasons") else ""
            suffix += " · " + t("Conservé") if record.get("selected_in_portfolio") else ""
            # Put the game identity first so it survives combo-box elision.
            identity = game_rank_label(record.get("rank")) + " · " + format_rank_score(record.get("rank_score"))
            name = str(record.get("card_name") or record.get("uma_name") or "—")
            self.target.addItem(identity + " · " + name + suffix, i)
            self.target.setItemData(i, canonical_veteran_label(record) + suffix, Qt.ItemDataRole.ToolTipRole)
        self.role.addItem(t("Parent"), "parent")
        self.role.addItem(t("Futur grand-parent"), "grandparent")
        for key, item in model.get("contexts", {}).items():
            self.course.addItem(self._context_label(item, key), key)
        self.case_section = SummarySection(t("Explorer un autre cas"))
        self.case_section.content_layout.addLayout(controls)
        root.addWidget(self.case_section)
        scores = QHBoxLayout()
        self.score_labels = []
        self.score_identity_labels = []
        for title in ("Copie étudiée", "Copie comparée", "Écart comparée − étudiée"):
            card = QFrame()
            card.setObjectName("panel")
            layout = QVBoxLayout(card)
            heading = QLabel(t(title))
            heading.setObjectName("muted")
            heading.setWordWrap(True)
            value = QLabel("—")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            value.setStyleSheet(f"font-size: {css_point_size('heading')}; font-weight: 700;")
            layout.addWidget(heading)
            layout.addWidget(value)
            scores.addWidget(card, 1)
            self.score_identity_labels.append(heading)
            self.score_labels.append(value)
        root.addLayout(scores)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.drivers = QLabel("")
        self.drivers.setWordWrap(True)
        root.addWidget(self.drivers)
        self.tabs = QTabWidget()
        self.explanation = QTextBrowser()
        self.explanation.setAccessibleName(t("Comprendre les gains et les pertes"))
        self.tabs.addTab(self.explanation, t("Gains et pertes"))
        visual = QWidget()
        visual_layout = QVBoxLayout(visual)
        legend = QLabel(t("Deux branches alternatives, jamais une paire locale. Vert : copie étudiée. Bleu : copie comparée. Contours vert/rouge : surplus/déficit d’étoiles dans la branche, pas un verdict. Cliquer pour inspecter les facteurs."))
        legend.setWordWrap(True)
        visual_layout.addWidget(legend)
        actions = QHBoxLayout()
        self.history = QCheckBox(t("Afficher l’historique du farm (hors score GP)"))
        self.history.setVisible(False)
        self.node_picker = ThemedComboBox()
        self.node_picker.setAccessibleName(t("Facteurs du membre sélectionné"))
        self.node_picker.setMinimumContentsLength(16)
        self.node_picker.setSizeAdjustPolicy(ThemedComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.node_picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._auto_fit = True
        self._fitting = False
        self.zoom = ZoomControl(context, .8)
        self.fit_button = QPushButton(t("Ajuster"))
        fit = self.fit_button
        fit.setToolTip(t("Ajuster les deux branches à la largeur disponible."))
        actions.addWidget(self.history)
        actions.addWidget(self.node_picker, 1)
        actions.addWidget(fit)
        actions.addWidget(self.zoom)
        visual_layout.addLayout(actions)
        self.tree = TransferLineageTree(context, image_repository(context))
        self.tree_scroll = QScrollArea()
        self.tree_scroll.setWidgetResizable(True)
        self.tree_scroll.setWidget(self.tree)
        self.tree_scroll.viewport().installEventFilter(self)
        visual_layout.addWidget(self.tree_scroll, 1)
        self.inspector = QTextBrowser()
        self.inspector.setAccessibleName(t("Tous les facteurs de la carte"))
        self.inspector.setMaximumHeight(130)
        self.inspector_section = CollapsibleSection(t("Facteurs détaillés du membre sélectionné"))
        self.inspector_section.content_layout.addWidget(self.inspector)
        visual_layout.addWidget(self.inspector_section)
        credit = QLabel(t("Portraits : GameTora · cache local et réglage Images en ligne de l’application."))
        credit.setObjectName('muted')
        visual_layout.addWidget(credit)
        self.tabs.addTab(visual, t("Lignée comparée"))
        self.history.toggled.connect(self._render)
        self.node_picker.currentIndexChanged.connect(lambda: self._inspect_node(show_details=True))
        self.tree.node_selected.connect(self._select_node)
        self.zoom.zoom_requested.connect(self._manual_zoom)
        self.tree.zoom_changed.connect(self._tree_zoom_changed)
        fit.clicked.connect(self._fit_tree)
        self.matrix = QTableWidget(0, 5)
        self.matrix.setHorizontalHeaderLabels([t(s) for s in ("Contexte", "Ace critique", "Candidat", "Copie comparée", "Écart minimal")])
        self.matrix.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.matrix.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.matrix.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.matrix.verticalHeader().setVisible(False)
        self.matrix.setAlternatingRowColors(True)
        self.matrix.setShowGrid(False)
        self.matrix.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.matrix.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        enable_tabular_numbers(self.matrix)
        self.matrix.setAccessibleName(t("Écarts pour le même Ace"))
        self.matrix.setToolTip(t("Clique une ligne pour inspecter son Ace critique. Écart = copie comparée − copie étudiée."))
        self.matrix.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.tabs.addTab(self.matrix, t("Niches comparées"))
        self.browsers = []
        for label in ("Composantes du score", "Whites exactes", "Facteurs et G1", "Rôles préservés"):
            browser = QTextBrowser()
            browser.setAccessibleName(t(label))
            self.tabs.addTab(browser, t(label))
            self.browsers.append(browser)
        root.addWidget(self.tabs, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        root.addWidget(close)
        self._matrix_rows: list[tuple[str, int]] = []
        self.target.currentIndexChanged.connect(lambda: self._refresh_matrix(preserve_selection=True))
        self.role.currentIndexChanged.connect(self._refresh_matrix)
        self.course.currentIndexChanged.connect(self._fill_aces)
        self.ace.currentIndexChanged.connect(self._render)
        self.matrix.cellClicked.connect(self._select_witness)
        self.tabs.currentChanged.connect(lambda: QTimer.singleShot(0, self._fit_tree) if self._auto_fit else None)
        self._refresh_matrix()
        QTimer.singleShot(0, self._fit_tree)

    def eventFilter(self, watched, event):
        if watched is self.tree_scroll.viewport() and event.type() == QEvent.Type.Resize and self._auto_fit:
            QTimer.singleShot(0, self._fit_tree)
        return super().eventFilter(watched, event)

    def _tree_zoom_changed(self, value) -> None:
        self.zoom.set_zoom(value)
        if not self._fitting:
            self._auto_fit = False

    def _manual_zoom(self, value) -> None:
        self._auto_fit = False
        self.tree.set_zoom(value)

    def _fit_tree(self) -> None:
        self._auto_fit = True
        self._fitting = True
        try:
            self.tree.set_zoom(min(1.2, max(.75, (self.tree_scroll.viewport().width() - 4) / self.tree.BASE_WIDTH)))
        finally:
            self._fitting = False

    def select_example(self, example) -> bool:
        """Open the exact saved witness, rather than an unrelated best score."""
        key, role = example.get("context_key"), example.get("role")
        aces = self.model.get("contexts", {}).get(key, {}).get("aces", [])
        index = next((i for i, ace in enumerate(aces)
                      if ace.get("card_id") == example.get("ace_card_id")), None)
        target_id = (example.get("target") or {}).get("trained_chara_id")
        target_index = next((i for i, r in enumerate(self.alternatives) if r.get("trained_chara_id") == target_id), None)
        if target_id is not None and target_index is None:
            return False
        if target_index is not None:
            self.target.setCurrentIndex(self.target.findData(target_index))
        role_index, course_index = self.role.findData(role), self.course.findData(key)
        if index is None or role_index < 0 or course_index < 0:
            return False
        self.role.setCurrentIndex(role_index)
        self.course.setCurrentIndex(course_index)
        self._fill_aces()
        self.ace.setCurrentIndex(self.ace.findData(index))
        self.matrix.clearSelection()
        self._render()
        self.tabs.setCurrentIndex(0)
        return True

    def _html_table(self, headers, rows) -> str:
        return "<table width='100%' cellspacing='0' cellpadding='7'><tr>" + "".join(
            f"<th align='left'>{escape(str(h))}</th>" for h in headers
        ) + "</tr>" + "".join("<tr>" + "".join(f"<td>{v}</td>" for v in row) + "</tr>" for row in rows) + "</table>"

    def _context_label(self, item: dict, key: str) -> str:
        prefix = self.context.t("Permanent") if item.get("scope") == "permanent" else str(item.get("label") or key).split(" · ")[0]
        profile = [profile_label(kind, str(item[kind]), self.context.language)
                   for kind in ("surface", "distance", "style") if item.get(kind)]
        return " · ".join([prefix, *profile])

    @staticmethod
    def _delta(value: float) -> str:
        color = "#78d6ad" if value >= 0 else "#ff8e98"
        return f"<b style='color:{color}'>{value:+.3f}</b>"

    def _refresh_matrix(self, *_args, preserve_selection=False) -> None:
        if self.target.currentData() is None:
            return
        current_key, current_ace = self.course.currentData(), self.ace.currentData()
        target = self.alternatives[self.target.currentData()]
        role = self.role.currentData()
        rows = []
        group = str(self.candidate.get("comparison_group") or "")
        for key, item in self.model.get("contexts", {}).items():
            left = self.candidate.get("comparison_profiles", {}).get(role, {}).get(key, [])
            right = target.get("comparison_profiles", {}).get(role, {}).get(key, [])
            relevant = self.model.get("relevant_aces", {}).get(group, {}).get(role, {}).get(key)
            allowed = set(relevant or []) if "relevant_aces" in self.model else set(range(len(left)))
            comparable = [(r - l, i, l, r) for i, (l, r) in enumerate(zip(left, right))
                          if i in allowed and l is not None and r is not None]
            if comparable:
                delta, i, l, r = min(comparable)
                rows.append((delta, key, i, l, r, item))
        rows.sort(key=lambda row: (row[0], row[1]))
        self.matrix.setRowCount(len(rows))
        self._matrix_rows = []
        for row_index, (delta, key, i, left, right, item) in enumerate(rows):
            self._matrix_rows.append((key, i))
            ace = item["aces"][i]
            cells = [self._context_label(item, key), str(ace.get("card_name") or ace.get("uma_name") or '—'),
                     f"{left:.3f}", f"{right:.3f}", f"{delta:+.3f}"]
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column >= 2:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.matrix.setItem(row_index, column, cell)
        best = self.candidate.get(f'best_{role}_context') or {}
        best_key = best.get('context_key')
        if preserve_selection and current_key in self.model.get('contexts', {}) and current_ace is not None:
            self.matrix.clearSelection()
            self.course.setCurrentIndex(self.course.findData(current_key))
            self._fill_aces()
            self.ace.setCurrentIndex(self.ace.findData(current_ace))
            self._render()
        elif best_key in self.model.get('contexts', {}) and rows:
            # Start from a known use of this copy. The matrix remains available
            # for inspecting the least favourable witness in every context.
            self.matrix.clearSelection()
            self.course.setCurrentIndex(self.course.findData(best_key))
            self._fill_aces()
            aces = self.model['contexts'][best_key]['aces']
            index = next((i for i, ace in enumerate(aces) if ace['card_id'] == best.get('ace_card_id')), 0)
            self.ace.setCurrentIndex(index)
            self._render()
        elif rows:
            self.matrix.selectRow(0)
            self._select_witness(0, 0)
        else:
            self._fill_aces()

    def _select_witness(self, row: int, _column: int) -> None:
        key, ace_index = self._matrix_rows[row]
        self.course.setCurrentIndex(self.course.findData(key))
        self._fill_aces()
        self.ace.setCurrentIndex(ace_index)
        self._render()

    def _fill_aces(self, *_args) -> None:
        self.ace.blockSignals(True)
        self.ace.clear()
        key = self.course.currentData()
        for i, ace in enumerate(self.model.get("contexts", {}).get(key, {}).get("aces", [])):
            self.ace.addItem(str(ace.get("card_name") or ace.get("uma_name") or '—'), i)
        self.ace.blockSignals(False)
        self._render()

    def _render(self, *_args) -> None:
        t = self.context.t
        self.explanation.clear()
        for label in self.score_labels:
            label.setText("—")
        self.history.setVisible(self.role.currentData() == "grandparent")
        if self.ace.currentData() is None or self.target.currentData() is None:
            self.tree.set_nodes({})
            self.summary.setText(t("Aucun Ace disponible dans ce contexte."))
            self.drivers.clear()
            self.inspector.clear()
            for browser in self.browsers:
                browser.clear()
            return
        target = self.alternatives[self.target.currentData()]
        for heading, title, record in zip(self.score_identity_labels, ('Copie étudiée', 'Copie comparée'), (self.candidate, target)):
            heading.setText(t(title) + ' · ' + game_rank_label(record.get('rank')) + ' · '
                            + format_rank_score(record.get('rank_score')) + '\n' + t('Indice du modèle'))
        role, key, ace_index = self.role.currentData(), self.course.currentData(), self.ace.currentData()
        left = comparison_evaluation(self.candidate, self.model, key, ace_index, role)
        right = comparison_evaluation(target, self.model, key, ace_index, role)
        self.case_section.set_summary(self.role.currentText() + " · " + self.course.currentText()
                                      + "\n" + t("Ace cible") + " : " + self.ace.currentText())
        protected = bool(self.candidate.get("manual_protection_reasons"))
        self.identity.setText(canonical_veteran_label(self.candidate)
                              + (" · " + t("Protégé — diagnostic seulement") if protected else ""))
        if left["score"] is None or right["score"] is None:
            self.summary.setText(t("Cette cible ne peut pas utiliser son propre personnage comme parent."))
            self.tree.set_nodes({})
            self.inspector.clear()
            self.drivers.clear()
            for browser in self.browsers:
                browser.clear()
            return
        for record, evaluation in ((self.candidate, left), (target, right)):
            stored = record.get("comparison_profiles", {}).get(role, {}).get(key, [])
            if ace_index < len(stored) and stored[ace_index] is not None and abs(stored[ace_index] - evaluation["score"]) > 1e-5:
                self.summary.setText(t("Le moteur actuel ne reproduit pas ce score historique. Les valeurs enregistrées restent visibles dans les niches comparées ; relance l’analyse pour obtenir une décomposition actualisée."))
                self.tree.set_nodes({})
                self.inspector.clear()
                self.drivers.clear()
                for browser in self.browsers:
                    browser.clear()
                return
        self.history.setVisible(role == 'grandparent')
        nodes = comparison_nodes((self.candidate, target), role, self.history.isChecked(),
                                 self.model['contexts'][key].get('skill_weights'))
        self.tree.retranslate()
        self.tree.set_nodes(nodes)
        previous = self.node_picker.currentData()
        self.node_picker.blockSignals(True)
        self.node_picker.clear()
        for position, node in nodes.items():
            self.node_picker.addItem(self.tree._role_labels[position] + ' · ' + canonical_veteran_label(node), position)
        self.node_picker.setCurrentIndex(max(0, self.node_picker.findData(previous)))
        self.node_picker.blockSignals(False)
        self._inspect_node()
        self.tree.set_selected_node(self.node_picker.currentData())
        delta = right["score"] - left["score"]
        self.score_labels[0].setText(f"{left['score']:.3f}")
        self.score_labels[1].setText(f"{right['score']:.3f}")
        direction = t("Avantage à la copie comparée") if delta > .0005 else (
            t("Avantage à la copie étudiée") if delta < -.0005 else t("Indices équivalents"))
        self.score_labels[2].setText(f"{delta:+.3f} · " + direction)
        for label, record in zip(self.score_labels, (self.candidate, target)):
            label.setToolTip(canonical_veteran_label(record))
        aptitudes = left['ace'].get('target_aptitudes') or {}
        aptitude_text = " / ".join(str(aptitudes.get(d, {}).get('label') or '—') for d in ('surface', 'distance', 'style'))
        exploratory = any(int(aptitudes.get(d, {}).get('rank') or 0) < 6 for d in ('surface', 'distance', 'style'))
        aptitude_text = t("Aptitudes de l’Ace : surface / distance / style") + " · " + aptitude_text
        if exploratory:
            aptitude_text += " · " + t("Profil exploratoire : aptitudes à relever")
        self.summary.setText(t("Un écart positif favorise la copie comparée.") + "\n" + aptitude_text)
        explanation = comparison_explanation(self.candidate, target, self.model, key, ace_index, role,
                                             evaluations=(left, right))
        self.explanation.setHtml(explanation_html(explanation, t))
        labels = {"blue": "Bleues", "distance_s": "Distance S", "surface_aptitude": "Aptitude surface",
                  "pink_other": "Autres roses", "pink": "Roses", "white_skill": "Whites",
                  "white_generation": "Génération White", "race_scenario": "Course / scénario",
                  "unique": "Unique", "g1_potential": "Potentiel G1", "affinity": "Affinité"}
        changes = sorted(((component, right['contributions'][component] - left['contributions'][component])
                          for component in left['weights']), key=lambda item: -abs(item[1]))
        self.drivers.setText(t("Principaux écarts de points du modèle") + " · " + " ; ".join(
            t(labels.get(component, component)) + f" {value:+.3f}" for component, value in changes[:3]))
        components = []
        weight_total = sum(max(0.0, float(w)) for w in left["weights"].values()) or 1.0
        for component, weight in left["weights"].items():
            l, r = left["contributions"][component], right["contributions"][component]
            components.append([escape(t(labels.get(component, component))), f"{max(0.0, float(weight)) / weight_total:.1%}",
                               f"{left['components'].get(component, 0):.3f}", f"{right['components'].get(component, 0):.3f}",
                               f"{l:.3f}", f"{r:.3f}", self._delta(r - l)])
        components.append(["<b>" + t("Total") + "</b>", "", "", "", f"{left['score']:.3f}",
                           f"{right['score']:.3f}", self._delta(delta)])
        component_html = self._html_table([t(s) for s in ("Composante", "Poids", "Score candidat", "Score comparé", "Points candidat", "Points comparés", "Écart")], components)
        if role == "grandparent":
            component_html += "<p>" + escape(t("Le score GP porte sur les facteurs propres. Génération White décrit l’historique du farm, avec un poids nul dans ce prototype ; ce n’est pas une probabilité d’héritage de l’Ace ni un coût de refarm.")) + "</p>"
        self.browsers[0].setHtml(component_html)
        whites = [white_inventory(evaluation) for evaluation in (left, right)]
        white_rows = []
        for skill in sorted(set(whites[0]) | set(whites[1]), key=lambda s: (-(max(float(d.get(s, {}).get('contribution', 0)) for d in whites)), s)):
            l, r = [d.get(skill, {}) for d in whites]
            def probability(item):
                value = item.get("probability_at_least_once")
                return f"{float(value):.1%}" if value is not None else "—"
            name = self.model.get("skill_labels", {}).get(skill) or l.get("name") or r.get("name") or skill.replace("_", " ")
            white_rows.append([escape(str(name)),
                               f"{float(self.model['contexts'][key]['skill_weights'].get(skill, 0)):.3f}",
                               str(l.get("carrier_count", 0)), probability(l), str(r.get("carrier_count", 0)), probability(r),
                               f"{float(l.get('contribution', 0)):.4f}", f"{float(r.get('contribution', 0)):.4f}",
                               self._delta(float(r.get("contribution", 0)) - float(l.get("contribution", 0)))])
        self.browsers[1].setHtml("<p>" + escape(t("Chaque White est distinguée. Les contributions ci-dessous précèdent la saturation du score White.")) + "</p>"
                                + self._html_table([t(s) for s in ("White", "Poids", "Copies candidat", "P candidat", "Copies comparées", "P comparée", "Valeur candidat", "Valeur comparée", "Écart")], white_rows))
        inventories = [factor_inventory(record, role) for record in (self.candidate, target)]
        factor_rows = []
        for factor in sorted(set(inventories[0]) | set(inventories[1])):
            l, r = [d.get(factor, {}) for d in inventories]
            def stars(item):
                carrier_names = {"parent": "P", "candidate": "GP", "grandparent_1": "GP1", "grandparent_2": "GP2"}
                return f"{item.get('stars', 0)}★ · " + ", ".join(f"{carrier_names.get(carrier, carrier)}: {n}★" for carrier, n in item.get("carriers", []))
            factor_labels = {"blue_stat": "Bleues", "red_aptitude": "Roses", "white_skill": "Whites",
                             "white_race": "Course", "scenario": "Scénario", "unique": "Unique"}
            factor_rows.append([escape(str(l.get("name") or r.get("name") or factor[1])),
                                escape(t(factor_labels.get(factor[0], factor[0]))), escape(stars(l)), escape(stars(r)),
                                self._delta(float(r.get("stars", 0)) - float(l.get("stars", 0)))])
        g1_sets = [set(record["comparison_veteran"].get("g1_wins", {}).get("names", [])) for record in (self.candidate, target)]
        g1_rows = [[escape(name), "✓" if name in g1_sets[0] else "—", "✓" if name in g1_sets[1] else "—"]
                   for name in sorted(g1_sets[0] | g1_sets[1])]
        factor_html = "<p>" + escape(t("Parent : facteur propre et deux GP. Futur GP : facteur propre. Les étoiles des copies répétées restent visibles par porteur.")) + "</p>"
        factor_html += self._html_table([t(s) for s in ("Spark", "Type", "Candidat", "Copie comparée", "Écart")], factor_rows)
        factor_html += "<h3>G1</h3>" + self._html_table([t(s) for s in ("Course", "Candidat", "Copie comparée")], g1_rows)
        self.browsers[2].setHtml(factor_html)
        assets = []
        for title, record in (("Candidat", self.candidate), ("Copie comparée", target)):
            assets.append("<h3>" + escape(t(title)) + "</h3>")
            if record.get("manual_protection_reasons"):
                assets.append("<p>" + escape(t("Protégé — diagnostic seulement")) + "</p>")
            items = record.get("portfolio_required_for") or []
            asset_labels = {"performance": "Niche compétitive", "identity": "Costume",
                            "blue_3star": "Bleues", "pink_3star": "Roses", "g1_pair": "G1",
                            "protected_skill": "Whites", "protected_package": "Package"}
            assets.append(self._html_table([t(s) for s in ("Patrimoine", "Usage")],
                         [[escape(t(asset_labels.get(str(item.get("kind")), str(item.get("kind"))))), escape(str(item.get("label")))] for item in items]))
            if not items:
                assets.append("<p>" + escape(t("Aucun usage exclusif dans le portefeuille conservé.")) + "</p>")
        self.browsers[3].setHtml("".join(assets))

    def _select_node(self, key):
        self.node_picker.setCurrentIndex(self.node_picker.findData(key))
        self._inspect_node(show_details=True)

    def _inspect_node(self, *_args, show_details=False):
        key = self.node_picker.currentData()
        self.tree.set_selected_node(key)
        if show_details:
            self.inspector_section.toggle.setChecked(True)
        self.inspector.setHtml(node_detail_html(self.tree.nodes.get(key), self.tree._role_labels.get(key, ''), self.context.t))

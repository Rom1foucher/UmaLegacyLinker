from __future__ import annotations

import copy
import json
import math
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from i18n import scoring_label, translate_text

# `scoring_label` is a flat leaf-name lookup shared with course_conditions,
# which reuses the same "parent_branch" / "parent_pair" leaf names for its own
# per-mode overrides. Give the mode_weights breadcrumb, editor title and
# distribution list their own more specific French source wording here
# instead of changing the shared dict, so course_conditions keeps its
# current generic labels. Routed through translate_text like every other
# source string, so the EN side stays covered by tests/check_i18n.py.
_MODE_WEIGHTS_LABEL_OVERRIDES = {
    "parent_branch": "Branche parent",
    "parent_pair": "Paire de parents finale",
}


def _mode_weights_aware_label(path: tuple[str, ...], key: str, language: str) -> str:
    if path and path[0] == "mode_weights":
        override = _MODE_WEIGHTS_LABEL_OVERRIDES.get(key)
        if override is not None:
            return str(translate_text(override, language))
    return scoring_label(key, language)
from scoring_config import (
    ScoringConfigError,
    build_overrides,
    count_override_leaves,
    deep_merge,
    get_path_value,
    iter_leaf_paths,
    load_effective_scoring_config,
    read_json_object,
    set_path_value,
    validate_scoring_config,
    write_json_object,
)
from ui_qt.components import (
    CollapsibleSection,
    PageHeader,
    PathPicker,
    ThemedComboBox,
    muted_label,
    section_label,
)
from ui_qt.context import AppContext, LineageContextState
from ui_qt.distribution_chart import DistributionDonut
from ui_qt.curve_editor import CurveEditor
from ui_qt.core import (
    default_scoring_path,
    default_skill_priorities_path,
    open_path,
    user_scoring_overrides_path,
    user_skill_priorities_path,
)
from ui_qt.weight_controls import (
    CATEGORY_SOURCES,
    is_percentage_setting,
    is_probability_setting,
    is_threshold_percentage,
    percentage_display,
    percentage_limit,
    relative_group_paths,
    relative_group_shares,
    relative_group_shares_with_value,
    weight_category,
    weight_sort_key,
    weight_subcategory,
)
from ui_qt.weight_help import WeightHelp, describe_weight


HIDDEN_KEYS = {
    "schema_version",
    "description",
    "formula_notes",
    "notes",
    "weight_source",
}


def _is_primary_setting(path: tuple[str, ...]) -> bool:
    """Keep the default view focused on broad, high-impact preferences."""

    if not path:
        return False
    root = path[0]
    if root == "mode_weights":
        return True
    if root == "blue_stat_weights_by_distance" and len(path) == 3:
        return True
    if root == "blue_score_influence_by_distance":
        return True
    if root == "aptitude_inheritance" and "dimension_weights_by_mode" in path:
        return True
    if root == "future_grandparent_heuristics" and "pink_dimension_weights" in path:
        return True
    return False


def _editor_text(value: object) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    return str(value)


def _compact_number(value: object, digits: int = 1) -> str:
    """Render UI metrics without exposing implementation-level precision."""

    rendered = f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    return rendered or "0"


class WeightsPage(QWidget):
    def __init__(self, context: AppContext, parent=None):
        super().__init__(parent)
        self.context = context
        self.default: dict[str, Any] = {}
        self.current: dict[str, Any] = {}
        self._all_rows: list[dict[str, Any]] = []
        self._selected_path: tuple[str, ...] | None = None
        self._editor_kind = "none"
        self._editor_reference: object = None
        self._editor_original: object = None
        self._percentage_is_probability = False
        self._slider_scale = 10.0
        self._relative_paths: tuple[tuple[str, ...], ...] = ()
        self._tree_items: dict[tuple[str, ...], QTreeWidgetItem] = {}
        self._active_help: WeightHelp | None = None
        self._editor_loading = False
        self._editor_pending = False
        self._selection_guard = False
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(12)
        self.header = PageHeader("", "")
        root.addWidget(self.header)

        active = QFrame()
        active.setObjectName("weightsToolbar")
        active_layout = QHBoxLayout(active)
        active_layout.setContentsMargins(16, 11, 16, 11)
        active_copy = QVBoxLayout()
        self.active_check = QCheckBox("")
        self.active_check.setChecked(
            context.lineage_state().use_custom_scoring
        )
        self.status = muted_label("")
        active_copy.addWidget(self.active_check)
        active_copy.addWidget(self.status)
        active_layout.addLayout(active_copy, 1)
        self.import_button = QPushButton("")
        self.export_button = QPushButton("")
        self.save_button = QPushButton("")
        self.save_button.setObjectName("primary")
        active_layout.addWidget(self.import_button)
        active_layout.addWidget(self.export_button)
        active_layout.addWidget(self.save_button)
        root.addWidget(active)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        navigation = QFrame()
        navigation.setObjectName("weightsNavigationPanel")
        navigation.setMinimumWidth(300)
        navigation_layout = QVBoxLayout(navigation)
        navigation_layout.setContentsMargins(13, 13, 13, 12)
        navigation_layout.setSpacing(8)
        navigation_head = QHBoxLayout()
        self.settings_title = section_label("")
        self.visible_count = muted_label("")
        navigation_head.addWidget(self.settings_title)
        navigation_head.addWidget(self.visible_count, 1, Qt.AlignmentFlag.AlignRight)
        self.search = QLineEdit()
        self.search.setClearButtonEnabled(True)
        self.category_filter_label = muted_label("")
        self.category_combo = ThemedComboBox()
        self.changed_only = QCheckBox("")
        self.show_advanced = QCheckBox("")
        navigation_layout.addLayout(navigation_head)
        navigation_layout.addWidget(self.search)
        navigation_layout.addWidget(self.category_filter_label)
        navigation_layout.addWidget(self.category_combo)
        navigation_layout.addWidget(self.changed_only)
        navigation_layout.addWidget(self.show_advanced)

        self.tree = QTreeWidget()
        self.tree.setObjectName("weightsTree")
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(True)
        self.tree.setItemsExpandable(False)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setMouseTracking(True)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.setToolTipDuration(14_000)
        self.tree.setIndentation(18)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.tree.header().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        navigation_layout.addWidget(self.tree, 1)
        self.hover_hint = muted_label("")
        self.reset_all_button = QPushButton("")
        navigation_layout.addWidget(self.hover_hint)
        navigation_actions = QHBoxLayout()
        navigation_actions.addStretch(1)
        navigation_actions.addWidget(self.reset_all_button)
        navigation_layout.addLayout(navigation_actions)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        editor = QFrame()
        editor.setObjectName("weightsEditorPanel")
        editor.setMinimumWidth(350)
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(19, 17, 19, 17)
        editor_layout.setSpacing(9)
        self.editor_breadcrumb = muted_label("")
        self.editor_title = section_label("")
        pills = QVBoxLayout()
        pills.setSpacing(5)
        scope_and_type = QHBoxLayout()
        scope_and_type.setSpacing(6)
        self.scope_badge = QLabel("")
        self.scope_badge.setObjectName("pill")
        self.type_badge = QLabel("")
        self.type_badge.setObjectName("pill")
        self.state_badge = QLabel("")
        self.state_badge.setObjectName("pillAccent")
        scope_and_type.addWidget(self.scope_badge)
        scope_and_type.addWidget(self.type_badge)
        scope_and_type.addStretch(1)
        state_row = QHBoxLayout()
        state_row.addWidget(self.state_badge)
        state_row.addStretch(1)
        pills.addLayout(scope_and_type)
        pills.addLayout(state_row)
        self.editor_summary = QLabel("")
        self.editor_summary.setObjectName("settingSummary")
        self.editor_summary.setWordWrap(True)

        impact = QFrame()
        impact.setObjectName("infoCallout")
        impact_layout = QVBoxLayout(impact)
        impact_layout.setContentsMargins(13, 11, 13, 11)
        impact_layout.setSpacing(4)
        self.impact_title = QLabel("")
        self.impact_title.setObjectName("calloutTitle")
        self.impact_text = QLabel("")
        self.impact_text.setWordWrap(True)
        impact_layout.addWidget(self.impact_title)
        impact_layout.addWidget(self.impact_text)

        control = QFrame()
        control.setObjectName("subtlePanel")
        control_layout = QVBoxLayout(control)
        control_layout.setContentsMargins(14, 12, 14, 12)
        control_layout.setSpacing(7)
        self.current_label = QLabel("")
        self.value_stack = QStackedWidget()
        self.value_stack.setMaximumHeight(90)

        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(0, 8, 0, 8)
        self.empty_label = muted_label("")
        empty_layout.addWidget(self.empty_label)

        self.bool_page = QWidget()
        bool_layout = QVBoxLayout(self.bool_page)
        bool_layout.setContentsMargins(0, 6, 0, 6)
        self.bool_edit = QCheckBox("")
        bool_layout.addWidget(self.bool_edit)

        self.percent_page = QWidget()
        percent_layout = QVBoxLayout(self.percent_page)
        percent_layout.setContentsMargins(0, 5, 0, 5)
        percent_row = QHBoxLayout()
        self.percent_slider = QSlider(Qt.Orientation.Horizontal)
        self.percent_spin = QDoubleSpinBox()
        self.percent_spin.setDecimals(2)
        self.percent_spin.setSingleStep(0.5)
        self.percent_spin.setSuffix(" %")
        self.percent_spin.setMinimumWidth(120)
        percent_row.addWidget(self.percent_slider, 1)
        percent_row.addWidget(self.percent_spin)
        self.percent_range = muted_label("")
        percent_layout.addLayout(percent_row)
        percent_scale = QHBoxLayout()
        self.percent_low = muted_label("")
        self.percent_high = muted_label("")
        percent_scale.addWidget(self.percent_low)
        percent_scale.addStretch(1)
        percent_scale.addWidget(self.percent_high, 0, Qt.AlignmentFlag.AlignRight)
        percent_layout.addWidget(self.percent_range, 0, Qt.AlignmentFlag.AlignCenter)
        percent_layout.addLayout(percent_scale)

        self.integer_page = QWidget()
        integer_layout = QVBoxLayout(self.integer_page)
        integer_layout.setContentsMargins(0, 5, 0, 5)
        self.integer_edit = QSpinBox()
        self.integer_edit.setRange(0, 2_147_483_647)
        integer_layout.addWidget(self.integer_edit)

        self.decimal_page = QWidget()
        decimal_layout = QVBoxLayout(self.decimal_page)
        decimal_layout.setContentsMargins(0, 5, 0, 5)
        self.decimal_edit = QDoubleSpinBox()
        self.decimal_edit.setRange(0.0, 1_000_000_000.0)
        self.decimal_edit.setDecimals(6)
        self.decimal_edit.setSingleStep(0.01)
        decimal_layout.addWidget(self.decimal_edit)

        self.enum_page = QWidget()
        enum_layout = QVBoxLayout(self.enum_page)
        enum_layout.setContentsMargins(0, 5, 0, 5)
        self.enum_edit = ThemedComboBox()
        enum_layout.addWidget(self.enum_edit)

        self.text_page = QWidget()
        text_layout = QVBoxLayout(self.text_page)
        text_layout.setContentsMargins(0, 5, 0, 5)
        self.text_edit = QLineEdit()
        text_layout.addWidget(self.text_edit)

        self.curve_page = QWidget()
        curve_layout = QVBoxLayout(self.curve_page)
        curve_layout.setContentsMargins(0, 5, 0, 5)
        self.curve_edit = CurveEditor()
        curve_layout.addWidget(self.curve_edit)

        self.structured_page = QWidget()
        structured_layout = QVBoxLayout(self.structured_page)
        structured_layout.setContentsMargins(0, 5, 0, 5)
        self.structured_edit = QPlainTextEdit()
        self.structured_edit.setMaximumHeight(150)
        structured_layout.addWidget(self.structured_edit)

        for page in (
            self.empty_page,
            self.bool_page,
            self.percent_page,
            self.integer_page,
            self.decimal_page,
            self.enum_page,
            self.text_page,
            self.curve_page,
            self.structured_page,
        ):
            self.value_stack.addWidget(page)

        self.editor_hint = muted_label("")
        control_layout.addWidget(self.current_label)
        control_layout.addWidget(self.value_stack)
        control_layout.addWidget(self.editor_hint)

        self.distribution_panel = QFrame()
        self.distribution_panel.setObjectName("subtlePanel")
        distribution_layout = QVBoxLayout(self.distribution_panel)
        distribution_layout.setContentsMargins(13, 11, 13, 11)
        distribution_layout.setSpacing(5)
        self.distribution_title = QLabel("")
        self.distribution_title.setObjectName("calloutTitle")
        self.distribution_explanation = muted_label("")
        self.distribution_chart = DistributionDonut()
        self.distribution_total = muted_label("")
        distribution_layout.addWidget(self.distribution_title)
        distribution_layout.addWidget(self.distribution_explanation)
        distribution_layout.addWidget(self.distribution_chart)
        distribution_layout.addWidget(self.distribution_total)
        self.distribution_panel.setVisible(False)

        comparison = QFrame()
        comparison.setObjectName("subtlePanel")
        comparison_layout = QHBoxLayout(comparison)
        comparison_layout.setContentsMargins(13, 9, 13, 9)
        comparison_copy = QVBoxLayout()
        comparison_copy.setSpacing(2)
        self.default_label = QLabel("")
        self.default_value = muted_label("")
        comparison_copy.addWidget(self.default_label)
        comparison_copy.addWidget(self.default_value)
        self.draft_state = QLabel("")
        self.draft_state.setObjectName("pill")
        comparison_layout.addLayout(comparison_copy, 1)
        comparison_layout.addWidget(self.draft_state)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("")
        self.apply_button.setObjectName("primary")
        self.reset_button = QPushButton("")
        self.reset_group_button = QPushButton("")
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.reset_group_button)
        buttons.addStretch(1)
        self.save_hint = muted_label("")

        editor_layout.addWidget(self.editor_breadcrumb)
        editor_layout.addWidget(self.editor_title)
        editor_layout.addLayout(pills)
        editor_layout.addWidget(self.editor_summary)
        editor_layout.addWidget(impact)
        editor_layout.addWidget(control)
        editor_layout.addWidget(self.distribution_panel)
        editor_layout.addWidget(comparison)
        editor_layout.addLayout(buttons)
        editor_layout.addWidget(self.save_hint)
        editor_layout.addStretch(1)
        editor_scroll.setWidget(editor)
        splitter.addWidget(navigation)
        splitter.addWidget(editor_scroll)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([390, 620])
        root.addWidget(splitter, 1)

        self.priorities = CollapsibleSection("")
        self.priority_status = muted_label("")
        self.priorities.content_layout.addWidget(self.priority_status)
        self.priority_help = muted_label("")
        self.priority_help.setWordWrap(True)
        self.priorities.content_layout.addWidget(self.priority_help)
        priority_row = QHBoxLayout()
        self.priority_picker = PathPicker(
            context.lineage_state().skill_priorities_path,
            title="Choisir un profil de priorités white",
            file_filter="JSON (*.json);;Tous les fichiers (*)",
        )
        self.create_priority_button = QPushButton("")
        self.open_priority_button = QPushButton("")
        self.reset_priority_button = QPushButton("")
        priority_row.addWidget(self.priority_picker, 1)
        self.priorities.content_layout.addLayout(priority_row)
        priority_actions = QHBoxLayout()
        priority_actions.addStretch(1)
        priority_actions.addWidget(self.create_priority_button)
        priority_actions.addWidget(self.open_priority_button)
        priority_actions.addWidget(self.reset_priority_button)
        self.priorities.content_layout.addLayout(priority_actions)
        root.addWidget(self.priorities)

        self.search.textChanged.connect(self.apply_filter)
        self.changed_only.toggled.connect(self.apply_filter)
        self.show_advanced.toggled.connect(self.apply_filter)
        self.category_combo.currentIndexChanged.connect(self.apply_filter)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemClicked.connect(self._tree_item_clicked)
        self.apply_button.clicked.connect(self.apply_value)
        self.reset_button.clicked.connect(self.reset_selected)
        self.reset_group_button.clicked.connect(self.reset_selected_group)
        self.reset_all_button.clicked.connect(self.reset_all)
        self.save_button.clicked.connect(self.save_profile)
        self.import_button.clicked.connect(self.import_profile)
        self.export_button.clicked.connect(self.export_profile)
        self.active_check.toggled.connect(self._active_changed)
        self.priority_picker.path_changed.connect(self._priority_changed)
        self.create_priority_button.clicked.connect(self.create_priority_copy)
        self.open_priority_button.clicked.connect(self.open_priority)
        self.reset_priority_button.clicked.connect(self.reset_priority)
        self.percent_slider.valueChanged.connect(self._percentage_slider_changed)
        self.percent_spin.valueChanged.connect(self._percentage_spin_changed)
        self.bool_edit.toggled.connect(self._update_bool_text)
        self.integer_edit.valueChanged.connect(self._editor_value_changed)
        self.decimal_edit.valueChanged.connect(self._editor_value_changed)
        self.enum_edit.currentIndexChanged.connect(self._editor_value_changed)
        self.text_edit.textEdited.connect(self._editor_value_changed)
        self.structured_edit.textChanged.connect(self._editor_value_changed)
        self.curve_edit.valueChanged.connect(self._editor_value_changed)
        self.context.lineage_changed.connect(self._sync_shared_settings)
        self.context.language_changed.connect(self._language_changed)
        self.reload()
        self.retranslate()

    def _language_changed(self, _language: str) -> None:
        self.retranslate()

    def reload(self) -> None:
        try:
            self.default, _overrides, self.current = load_effective_scoring_config(
                default_scoring_path(), user_scoring_overrides_path()
            )
        except (OSError, ScoringConfigError) as exc:
            QMessageBox.warning(self, self.context.t("Profil de pondération invalide"), self.context.t(str(exc)))
            self.default = read_json_object(default_scoring_path())
            self.current = copy.deepcopy(self.default)
        self._rebuild_rows()
        self._refresh_status()

    def _rebuild_rows(self) -> None:
        rows: list[dict[str, Any]] = []
        for path, value in iter_leaf_paths(self.current):
            if any(key in HIDDEN_KEYS or key.endswith("description") for key in path):
                continue
            try:
                default_value = get_path_value(self.default, path)
            except KeyError:
                default_value = None
            labels = [_mode_weights_aware_label(path, key, self.context.language) for key in path]
            help_info = describe_weight(path, value, self.context.language)
            help_info = WeightHelp(
                help_info.summary,
                help_info.impact,
                help_info.scope,
                help_info.low_label,
                help_info.high_label,
                advanced=not _is_primary_setting(path),
            )
            category_key = weight_category(path)
            category_source = dict(CATEGORY_SOURCES).get(category_key, "Autres")
            category_label = self.context.t(category_source)
            subcategory_key, subcategory_source, subcategory_order = weight_subcategory(path)
            subcategory_label = self.context.t(subcategory_source)
            active_value = self._display_value(
                path, value, default_value, source=self.current
            )
            default_display = self._display_value(
                path, default_value, default_value, source=self.default
            )
            changed = self._path_changed(path, value, default_value)
            rows.append(
                {
                    "label": " › ".join(labels),
                    "list_label": " › ".join(labels[1:] or labels),
                    "breadcrumb": f"{category_label} › {subcategory_label}",
                    "path_tuple": path,
                    "category": category_key,
                    "category_label": category_label,
                    "subcategory": subcategory_key,
                    "subcategory_label": subcategory_label,
                    "subcategory_order": subcategory_order,
                    "active": active_value,
                    "default": default_display,
                    "changed": changed,
                    "state": self.context.t("Modifié" if changed else "Défaut"),
                    "help": help_info,
                    "sort_key": weight_sort_key(path),
                    "_tooltip": (
                        f"{subcategory_label} › {labels[-1]}\n\n{help_info.summary}\n\n"
                        f"{self.context.t('Effet')} : {help_info.impact}\n\n"
                        f"{self.context.t('Actuel')} : {active_value}  ·  "
                        f"{self.context.t('Défaut')} : {default_display}"
                    ),
                }
            )
        self._all_rows = sorted(rows, key=lambda row: row["sort_key"])
        self._rebuild_categories()
        self.apply_filter()

    def _path_changed(
        self, path: tuple[str, ...], value: object, default_value: object
    ) -> bool:
        return value != default_value

    def _display_value(
        self,
        path: tuple[str, ...],
        value: object,
        reference: object | None = None,
        *,
        source: dict[str, Any] | None = None,
    ) -> str:
        group = relative_group_shares(source or self.current, path)
        if group:
            share = dict(group).get(path, 0.0)
            points = _compact_number(float(value) * 100.0, 1)
            effective = _compact_number(share * 100.0, 1)
            return (
                self.context.t("{points} pts · {share} % effectifs")
                .replace("{points}", points)
                .replace("{share}", effective)
            )
        if is_percentage_setting(path, value if reference is None else reference):
            if is_probability_setting(path):
                return percentage_display(value)
            rendered = _compact_number(value, 2)
            return f"×{rendered}"
        if isinstance(value, bool):
            return self.context.t("Activé" if value else "Désactivé")
        if isinstance(value, (list, dict)):
            return self.context.t("{count} points de courbe").replace(
                "{count}", str(len(value))
            )
        if value == "floor":
            return self.context.t("Plancher")
        if value == "override":
            return self.context.t("Remplacement")
        return str(value)

    def _selected_category(self) -> str:
        return str(self.category_combo.currentData() or "all")

    def _rebuild_categories(self) -> None:
        selected = self._selected_category()
        counts: dict[str, int] = {}
        for row in self._all_rows:
            key = str(row["category"])
            counts[key] = counts.get(key, 0) + 1

        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        target_row = -1
        for key, source in CATEGORY_SOURCES:
            count = len(self._all_rows) if key == "all" else counts.get(key, 0)
            if key != "all" and not count:
                continue
            text = f"{self.context.t(source)}  ·  {count}"
            self.category_combo.addItem(text, key)
            if key == selected:
                target_row = self.category_combo.count() - 1
        if self.category_combo.count():
            if target_row < 0:
                target_row = self.category_combo.findData("global")
            self.category_combo.setCurrentIndex(target_row if target_row >= 0 else 0)
        self.category_combo.blockSignals(False)

    def _tree_headers(self) -> list[str]:
        return [
            self.context.t("Réglage"),
            self.context.t("Actuel"),
            self.context.t("État"),
        ]

    def _make_group_item(
        self,
        label: str,
        count: int,
        *,
        key: str,
        parent: QTreeWidgetItem | None = None,
        changed_count: int = 0,
    ) -> QTreeWidgetItem:
        item = (
            QTreeWidgetItem(parent)
            if parent is not None
            else QTreeWidgetItem(self.tree)
        )
        suffix = f"  ·  {count}"
        if changed_count:
            suffix += "  ·  " + self.context.t("{count} modifié(s)").replace(
                "{count}", str(changed_count)
            )
        item.setText(0, f"{label}{suffix}")
        item.setData(0, Qt.ItemDataRole.UserRole + 1, key)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setFirstColumnSpanned(True)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        is_category = key.startswith("category:")
        item.setSizeHint(0, QSize(0, 32 if is_category else 28))
        background = QColor("#17263a" if is_category else "#131f2f")
        foreground = QColor("#dce9f8" if is_category else "#aebfd3")
        for column in range(3):
            item.setBackground(column, QBrush(background))
            item.setForeground(column, QBrush(foreground))
        if changed_count:
            accent = QColor("#8de8ca")
            item.setForeground(0, QBrush(accent))
            item.setToolTip(
                0,
                self.context.t("Ce bloc contient {count} réglage(s) modifié(s).").replace(
                    "{count}", str(changed_count)
                ),
            )
        return item

    def _append_setting_item(
        self, parent: QTreeWidgetItem, row: dict[str, Any]
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent)
        item.setText(0, str(row["list_label"]))
        item.setText(1, str(row["active"]))
        item.setText(2, str(row["state"]))
        item.setData(0, Qt.ItemDataRole.UserRole, row)
        item.setSizeHint(0, QSize(0, 27))
        tooltip = str(row["_tooltip"])
        for column in range(3):
            item.setToolTip(column, tooltip)
        if row["changed"]:
            for column in range(3):
                font = item.font(column)
                font.setBold(True)
                item.setFont(column, font)
            item.setForeground(0, QBrush(QColor("#8de8ca")))
            item.setForeground(2, QBrush(QColor("#8de8ca")))
        else:
            item.setForeground(2, QBrush(QColor("#8192a8")))
        self._tree_items[tuple(row["path_tuple"])] = item
        return item

    def _tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Open or close a category/block with a single click anywhere on its row."""

        if item.data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        if item.childCount():
            item.setExpanded(not item.isExpanded())

    def apply_filter(self, *_args: object) -> None:
        query = self.search.text().strip().casefold()
        changed_only = self.changed_only.isChecked()
        show_advanced = self.show_advanced.isChecked()
        category = self._selected_category()
        rows = [
            row for row in self._all_rows
            if (not changed_only or row["changed"])
            and (show_advanced or not row["help"].advanced or row["changed"])
            and (category == "all" or row["category"] == category)
            and (
                not query
                or query
                in (
                    f"{row['label']} {row['subcategory_label']} {row['active']} {row['state']} "
                    f"{row['help'].summary} {row['help'].impact}"
                ).casefold()
            )
        ]
        previous = self._selected_path
        expanded = {
            str(item.data(0, Qt.ItemDataRole.UserRole + 1))
            for index in range(self.tree.topLevelItemCount())
            for item in self._walk_tree(self.tree.topLevelItem(index))
            if item.isExpanded()
            and item.data(0, Qt.ItemDataRole.UserRole + 1) is not None
        }
        self.tree.blockSignals(True)
        self.tree.clear()
        self.tree.setHeaderLabels(self._tree_headers())
        self._tree_items = {}
        category_sources = dict(CATEGORY_SOURCES)
        rows_by_category: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            rows_by_category.setdefault(str(row["category"]), []).append(row)

        category_order = [
            key for key, _source in CATEGORY_SOURCES if key not in {"all", "other"}
        ]
        if "other" in rows_by_category:
            category_order.append("other")
        for category_key in category_order:
            category_rows = rows_by_category.get(category_key, [])
            if not category_rows:
                continue
            category_parent: QTreeWidgetItem | None = None
            if category == "all":
                category_parent = self._make_group_item(
                    self.context.t(category_sources.get(category_key, "Autres")),
                    len(category_rows),
                    key=f"category:{category_key}",
                    changed_count=sum(1 for row in category_rows if row["changed"]),
                )
            groups: dict[str, list[dict[str, Any]]] = {}
            for row in category_rows:
                groups.setdefault(str(row["subcategory"]), []).append(row)
            ordered_groups = sorted(
                groups.items(),
                key=lambda pair: (
                    min(int(item["subcategory_order"]) for item in pair[1]),
                    str(pair[1][0]["subcategory_label"]).casefold(),
                ),
            )
            for group_key, group_rows in ordered_groups:
                group_item = self._make_group_item(
                    str(group_rows[0]["subcategory_label"]),
                    len(group_rows),
                    key=f"group:{group_key}",
                    parent=category_parent,
                    changed_count=sum(1 for row in group_rows if row["changed"]),
                )
                for row in group_rows:
                    self._append_setting_item(group_item, row)

        for index in range(self.tree.topLevelItemCount()):
            for item in self._walk_tree(self.tree.topLevelItem(index)):
                group_key = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if group_key in expanded or query:
                    item.setExpanded(True)
        if not expanded and not query and self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            first.setExpanded(True)
            if category == "all" and first.childCount():
                first.child(0).setExpanded(True)
        self.tree.blockSignals(False)
        self.visible_count.setText(
            self.context.t("{shown} / {total} réglages")
            .replace("{shown}", str(len(rows)))
            .replace("{total}", str(len(self._all_rows)))
        )
        target_item = self._tree_items.get(previous) if previous else None
        if target_item is None and rows and not self._editor_pending:
            target_item = self._tree_items.get(tuple(rows[0]["path_tuple"]))
        if target_item is not None:
            parent = target_item.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.setCurrentItem(target_item)
        elif not self._editor_pending:
            self._show_selection(None)

    @staticmethod
    def _walk_tree(root: QTreeWidgetItem):
        yield root
        for index in range(root.childCount()):
            yield from WeightsPage._walk_tree(root.child(index))

    def selected_row(self) -> dict[str, Any] | None:
        item = self.tree.currentItem()
        row = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return row if isinstance(row, dict) else None

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if self._selection_guard:
            return
        row = (
            current.data(0, Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        if not isinstance(row, dict):
            return
        new_path = tuple(row["path_tuple"]) if row else None
        old_path = self._selected_path
        if self._editor_pending and old_path and new_path == old_path:
            return
        if self._editor_pending and old_path and new_path != old_path:
            if not self._commit_editor_value(show_warning=True):
                self._select_path(old_path)
                return
            self._selected_path = new_path
            self._rebuild_rows()
            return
        self._show_selection(row)

    def _select_path(self, path: tuple[str, ...]) -> None:
        item = self._tree_items.get(path)
        if item is None:
            return
        self._selection_guard = True
        self.tree.setCurrentItem(item)
        self._selection_guard = False

    def _show_selection(self, row: dict[str, Any] | None) -> None:
        if not row:
            self._selected_path = None
            self._editor_kind = "none"
            self._relative_paths = ()
            self._active_help = None
            self.distribution_panel.setVisible(False)
            self.editor_breadcrumb.setText("")
            self.editor_title.setText(self.context.t("Sélectionne un réglage"))
            self.scope_badge.setText(self.context.t("Aide contextuelle"))
            self.type_badge.setText("")
            self.state_badge.setText("")
            self.type_badge.setVisible(False)
            self.state_badge.setVisible(False)
            self.editor_summary.setText(
                self.context.t(
                    "Chaque réglage affiche ici son rôle, son impact et la direction de sa valeur."
                )
            )
            self.impact_title.setText(self.context.t("Comment utiliser cet écran"))
            self.impact_text.setText(
                self.context.t(
                    "Choisis un domaine, déplie un bloc de calcul, puis sélectionne un réglage. La recherche traverse toute l’arborescence."
                )
            )
            self.current_label.setText(self.context.t("Valeur active"))
            self.value_stack.setMaximumHeight(72)
            self.value_stack.setCurrentWidget(self.empty_page)
            self.default_value.setText("—")
            self.draft_state.setText("—")
            self.editor_hint.setText(
                self.context.t("Choisis un réglage dans la liste pour afficher le contrôle adapté.")
            )
            self.apply_button.setEnabled(False)
            self.reset_button.setEnabled(False)
            self.reset_group_button.setVisible(False)
            self.reset_group_button.setEnabled(False)
            self._editor_pending = False
            return
        path = tuple(row["path_tuple"])
        self._selected_path = path
        value = get_path_value(self.current, path)
        default = get_path_value(self.default, path)
        help_info = row.get("help") or describe_weight(path, value, self.context.language)
        self._active_help = help_info
        self.editor_breadcrumb.setText(str(row.get("breadcrumb") or ""))
        self.editor_title.setText(_mode_weights_aware_label(path, path[-1], self.context.language))
        self.scope_badge.setText(help_info.scope)
        self.type_badge.setVisible(True)
        self.state_badge.setVisible(True)
        self.editor_summary.setText(help_info.summary)
        self.impact_title.setText(self.context.t("Effet sur le classement"))
        self.impact_text.setText(help_info.impact)
        self._editor_loading = True
        try:
            self._configure_editor(path, value, default)
        finally:
            self._editor_loading = False
        self._editor_pending = False
        if self._editor_kind == "relative_weight":
            self.percent_low.setText(self.context.t("0 pt · ignoré"))
            self.percent_high.setText(self.context.t("Plus de points · plus d’impact"))
        elif self._editor_kind == "multiplier":
            self.percent_low.setText(self.context.t("×0 · ignoré"))
            self.percent_high.setText(self.context.t("×1 · référence"))
        else:
            self.percent_low.setText(help_info.low_label)
            self.percent_high.setText(help_info.high_label)
        self.default_value.setText(
            self._display_value(path, default, default, source=self.default)
        )
        changed = self._path_changed(path, value, default)
        self.state_badge.setText(
            self.context.t("Réglage avancé" if help_info.advanced else "Réglage standard")
        )
        self.state_badge.setObjectName("pillWarning" if help_info.advanced else "pill")
        self.state_badge.style().unpolish(self.state_badge)
        self.state_badge.style().polish(self.state_badge)
        self._set_draft_state(changed=changed, pending=False)
        self.apply_button.setEnabled(False)
        self.reset_button.setEnabled(changed)
        block_paths = self._selected_block_paths(path)
        self.reset_group_button.setVisible(len(block_paths) > 1)
        self.reset_group_button.setEnabled(self._block_changed(block_paths))

    def _set_draft_state(self, *, changed: bool, pending: bool) -> None:
        if pending:
            text = self.context.t("Modification à appliquer")
            object_name = "pillWarning"
        elif changed:
            text = self.context.t("Brouillon modifié")
            object_name = "pillAccent"
        else:
            text = self.context.t("Valeur d’origine")
            object_name = "pill"
        self.draft_state.setText(text)
        self.draft_state.setObjectName(object_name)
        self.draft_state.style().unpolish(self.draft_state)
        self.draft_state.style().polish(self.draft_state)

    def _editor_value_changed(self, *_args: object) -> None:
        if self._editor_loading or not self._selected_path:
            return
        try:
            pending = self._read_editor_value() != self._editor_original
        except ValueError:
            pending = True
        self._update_distribution_preview()
        self._editor_pending = pending
        current_value = get_path_value(self.current, self._selected_path)
        default_value = get_path_value(self.default, self._selected_path)
        current_changed = self._path_changed(
            self._selected_path, current_value, default_value
        )
        self._set_draft_state(changed=current_changed, pending=pending)
        self.apply_button.setEnabled(pending)
        self.reset_button.setEnabled(pending or current_changed)
        self.reset_group_button.setEnabled(
            pending or self._block_changed(self._selected_block_paths(self._selected_path))
        )

    def _set_editor_type(self, source: str) -> None:
        translated = self.context.t(source)
        self.current_label.setText(
            f"{self.context.t('Valeur active')} · {translated}"
        )
        self.type_badge.setText(translated)

    def _configure_editor(
        self, path: tuple[str, ...], value: object, default: object
    ) -> None:
        self._relative_paths = relative_group_paths(self.current, path)
        self.distribution_panel.setVisible(bool(self._relative_paths))
        self._editor_reference = default
        self._editor_original = copy.deepcopy(value)
        if self._relative_paths:
            raw_value = float(value)
            raw_default = float(default)
            points = raw_value * 100.0
            default_points = raw_default * 100.0
            limit = max(
                100.0,
                math.ceil(max(points, default_points, 1.0) / 25.0) * 25.0,
            )
            self._editor_kind = "relative_weight"
            self._percentage_is_probability = False
            self._slider_scale = 10.0
            self.percent_spin.setDecimals(1)
            self.percent_spin.setPrefix("")
            self.percent_spin.setSuffix(" pts")
            self.percent_spin.setSingleStep(0.5)
            self.percent_slider.blockSignals(True)
            self.percent_spin.blockSignals(True)
            self.percent_slider.setRange(0, int(round(limit * self._slider_scale)))
            self.percent_spin.setRange(0.0, max(1_000.0, limit))
            self.percent_slider.setValue(int(round(points * self._slider_scale)))
            self.percent_spin.setValue(points)
            self.percent_slider.blockSignals(False)
            self.percent_spin.blockSignals(False)
            self._set_percentage_range_label(limit)
            self.value_stack.setMaximumHeight(118)
            self.value_stack.setCurrentWidget(self.percent_page)
            self._set_editor_type("Poids indépendant")
            self.editor_hint.setText(
                self.context.t(
                    "Seul ce poids est modifié. La part effective affichée dans la roue est recalculée sans réécrire les autres valeurs."
                )
            )
            self._update_distribution_preview()
            return
        if self._is_curve_setting(path, default):
            self._editor_kind = "curve"
            x_probability = path[-1] in {"s_probability_curve", "distinct_skill_probability_curve"}
            y_probability = path[-1] == "distinct_skill_probability_curve"
            self.curve_edit.set_value(
                copy.deepcopy(value),
                x_probability=x_probability,
                y_probability=y_probability,
            )
            if x_probability:
                x_label = self.context.t("Probabilité (%)")
            else:
                x_label = self.context.t("Valeur d’entrée")
            y_label = self.context.t("Utilité (%)" if y_probability else "Score d’utilité")
            self.curve_edit.add_button.setText(self.context.t("Ajouter un point"))
            self.curve_edit.remove_button.setText(self.context.t("Supprimer le point"))
            self.curve_edit.set_labels(
                x_label,
                y_label,
                self.context.t(
                    "Déplace les points directement sur la courbe ou ajuste les valeurs dans le tableau. Les points restent ordonnés et la courbe reste croissante."
                ),
            )
            self.value_stack.setMaximumHeight(560)
            self.value_stack.setCurrentWidget(self.curve_page)
            self._set_editor_type("Courbe interactive")
            self.editor_hint.setText(
                self.context.t(
                    "Cette courbe transforme une probabilité ou un seuil brut en utilité de classement."
                )
            )
            return
        if isinstance(default, bool):
            self._editor_kind = "bool"
            self.bool_edit.blockSignals(True)
            self.bool_edit.setChecked(bool(value))
            self.bool_edit.blockSignals(False)
            self._update_bool_text(bool(value))
            self.value_stack.setMaximumHeight(62)
            self.value_stack.setCurrentWidget(self.bool_page)
            self._set_editor_type("Interrupteur")
            self.editor_hint.setText(
                self.context.t("Active ou désactive ce comportement dans le calcul.")
            )
            return

        if is_percentage_setting(path, default):
            self._percentage_is_probability = is_probability_setting(path)
            if not self._percentage_is_probability:
                self._editor_kind = "multiplier"
                self._slider_scale = 1_000.0
                self.percent_spin.setDecimals(2)
                limit = max(2.0, math.ceil(max(float(value), float(default))))
                self.percent_slider.blockSignals(True)
                self.percent_spin.blockSignals(True)
                self.percent_slider.setRange(0, int(round(limit * self._slider_scale)))
                self.percent_spin.setRange(0.0, max(10.0, limit))
                self.percent_spin.setPrefix("×")
                self.percent_spin.setSuffix("")
                self.percent_spin.setSingleStep(0.05)
                self.percent_slider.setValue(int(round(float(value) * self._slider_scale)))
                self.percent_spin.setValue(float(value))
                self.percent_slider.blockSignals(False)
                self.percent_spin.blockSignals(False)
                self._set_percentage_range_label(limit)
                self.value_stack.setMaximumHeight(118)
                self.value_stack.setCurrentWidget(self.percent_page)
                self._set_editor_type("Coefficient ×")
                self.editor_hint.setText(
                    self.context.t(
                        "Coefficient indépendant : ×1 est la valeur de référence. Il ne partage pas un budget de 100 % avec ses voisins."
                    )
                )
                return

            self._editor_kind = "percentage"
            self._slider_scale = 10.0
            self.percent_spin.setDecimals(2)
            self.percent_spin.setPrefix("")
            self.percent_spin.setSuffix(" %")
            self.percent_spin.setSingleStep(0.5)
            limit = percentage_limit(path, value, default)
            percent = float(value) * 100.0
            self.percent_slider.blockSignals(True)
            self.percent_spin.blockSignals(True)
            self.percent_slider.setRange(0, int(round(limit * 10.0)))
            self.percent_spin.setRange(
                0.0, limit if self._percentage_is_probability else max(1_000.0, limit)
            )
            self.percent_slider.setValue(int(round(percent * 10.0)))
            self.percent_spin.setValue(percent)
            self.percent_slider.blockSignals(False)
            self.percent_spin.blockSignals(False)
            self._set_percentage_range_label(limit)
            self.value_stack.setMaximumHeight(118)
            self.value_stack.setCurrentWidget(self.percent_page)
            if is_threshold_percentage(path):
                self._set_editor_type("Seuil en %")
                hint = "Seuil absolu borné de 0 à 100 %. Il n’est pas renormalisé avec d’autres valeurs."
            else:
                self._set_editor_type("Probabilité")
                hint = "Probabilité bornée à 100 %. Le champ numérique permet un réglage précis."
            self.editor_hint.setText(self.context.t(hint))
            return

        if isinstance(default, int) and not isinstance(default, bool):
            self._editor_kind = "integer"
            self.integer_edit.setValue(int(value))
            self.value_stack.setMaximumHeight(72)
            self.value_stack.setCurrentWidget(self.integer_page)
            self._set_editor_type("Nombre entier")
            self.editor_hint.setText(
                self.context.t("Valeur entière positive ou nulle.")
            )
            return

        if isinstance(default, float):
            self._editor_kind = "decimal"
            self.decimal_edit.setValue(float(value))
            self.value_stack.setMaximumHeight(72)
            self.value_stack.setCurrentWidget(self.decimal_page)
            self._set_editor_type("Nombre décimal")
            self.editor_hint.setText(
                self.context.t("Valeur décimale positive ou nulle.")
            )
            return

        enum_options = self._enum_options(path)
        if enum_options:
            self._editor_kind = "enum"
            self.enum_edit.clear()
            for label, data in enum_options:
                self.enum_edit.addItem(label, data)
            index = self.enum_edit.findData(value)
            self.enum_edit.setCurrentIndex(index if index >= 0 else 0)
            self.value_stack.setMaximumHeight(72)
            self.value_stack.setCurrentWidget(self.enum_page)
            self._set_editor_type("Choix")
            self.editor_hint.setText(
                self.context.t("Sélectionne le comportement appliqué par le moteur.")
            )
            return

        if isinstance(default, str):
            self._editor_kind = "text"
            self.text_edit.setText(str(value))
            self.value_stack.setMaximumHeight(72)
            self.value_stack.setCurrentWidget(self.text_page)
            self._set_editor_type("Texte")
            self.editor_hint.setText(
                self.context.t("Valeur textuelle utilisée par le moteur.")
            )
            return

        self._editor_kind = "structured"
        self.structured_edit.setPlainText(_editor_text(value))
        self.value_stack.setMaximumHeight(180)
        self.value_stack.setCurrentWidget(self.structured_page)
        self._set_editor_type("Courbe ou liste")
        self.editor_hint.setText(
            self.context.t("Éditeur avancé : conserve une liste JSON valide et ordonnée.")
        )

    @staticmethod
    def _is_curve_setting(path: tuple[str, ...], value: object) -> bool:
        if not isinstance(value, list) or len(value) < 2:
            return False
        if not all(
            isinstance(point, list)
            and len(point) == 2
            and all(isinstance(number, (int, float)) for number in point)
            for point in value
        ):
            return False
        return path[-1].endswith("_curve") or path[-1].endswith("_thresholds")

    def _enum_options(self, path: tuple[str, ...]) -> list[tuple[str, str]]:
        if path == ("transfer_helper", "analysis_mode"):
            return [
                (self.context.t("Rapide"), "fast"),
                (self.context.t("Audit exhaustif"), "exhaustive"),
            ]
        if path[:2] == ("course_conditions", "modes"):
            return [
                (self.context.t("Plancher"), "floor"),
                (self.context.t("Remplacement"), "override"),
            ]
        return []

    def _percentage_slider_changed(self, value: int) -> None:
        self.percent_spin.blockSignals(True)
        self.percent_spin.setValue(value / self._slider_scale)
        self.percent_spin.blockSignals(False)
        self._editor_value_changed()

    def _percentage_spin_changed(self, value: float) -> None:
        if value * self._slider_scale > self.percent_slider.maximum():
            if self._editor_kind == "multiplier":
                expanded = max(2.0, float(math.ceil(value)))
            else:
                expanded = max(100.0, float(int((value + 99.9999) // 100) * 100))
            self.percent_slider.setMaximum(
                int(round(expanded * self._slider_scale))
            )
            self._set_percentage_range_label(expanded)
        self.percent_slider.blockSignals(True)
        self.percent_slider.setValue(int(round(value * self._slider_scale)))
        self.percent_slider.blockSignals(False)
        self._editor_value_changed()

    def _set_percentage_range_label(self, maximum: float) -> None:
        if self._editor_kind == "relative_weight":
            self.percent_range.setText(
                self.context.t(
                    "Plage du slider : 0 à {maximum} points · la roue normalise le total"
                ).replace("{maximum}", f"{maximum:g}")
            )
            return
        if self._editor_kind == "multiplier":
            self.percent_range.setText(
                self.context.t("Plage du slider : ×0 à ×{maximum} · référence ×1").replace(
                    "{maximum}", f"{maximum:g}"
                )
            )
            return
        self.percent_range.setText(
            self.context.t("Plage du slider : 0 % à {maximum} %").replace(
                "{maximum}", f"{maximum:g}"
            )
        )

    def _update_bool_text(self, checked: bool) -> None:
        self.bool_edit.setText(self.context.t("Activé" if checked else "Désactivé"))
        self._editor_value_changed()

    def _read_editor_value(self) -> object:
        if self._editor_kind == "bool":
            return self.bool_edit.isChecked()
        if self._editor_kind == "percentage":
            value = self.percent_spin.value()
            if isinstance(self._editor_original, (int, float)) and abs(
                value - float(self._editor_original) * 100.0
            ) < 0.00005:
                return self._editor_original
            return value / 100.0
        if self._editor_kind == "relative_weight":
            value = self.percent_spin.value() / 100.0
            if isinstance(self._editor_original, (int, float)) and abs(
                value - float(self._editor_original)
            ) < 0.0000005:
                return self._editor_original
            return value
        if self._editor_kind == "multiplier":
            value = self.percent_spin.value()
            if isinstance(self._editor_original, (int, float)) and abs(
                value - float(self._editor_original)
            ) < 0.0000005:
                return self._editor_original
            return value
        if self._editor_kind == "integer":
            return self.integer_edit.value()
        if self._editor_kind == "decimal":
            return self.decimal_edit.value()
        if self._editor_kind == "enum":
            return self.enum_edit.currentData()
        if self._editor_kind == "text":
            return self.text_edit.text()
        if self._editor_kind == "curve":
            return self.curve_edit.value()
        if self._editor_kind == "structured":
            try:
                value = json.loads(self.structured_edit.toPlainText().strip())
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"JSON invalide, ligne {exc.lineno}, colonne {exc.colno}."
                ) from exc
            if isinstance(self._editor_reference, list) and not isinstance(value, list):
                raise ValueError("Une liste JSON est attendue.")
            if isinstance(self._editor_reference, dict) and not isinstance(value, dict):
                raise ValueError("Un objet JSON est attendu.")
            return value
        raise ValueError("Sélectionne un réglage.")

    def _update_distribution_preview(self) -> None:
        if not self._relative_paths or not self._selected_path:
            self.distribution_panel.setVisible(False)
            return
        selected_value = (
            self.percent_spin.value() / 100.0
            if self._editor_kind == "relative_weight"
            else float(get_path_value(self.current, self._selected_path))
        )
        distribution = relative_group_shares_with_value(
            self.current, self._selected_path, selected_value
        )
        items = [
            (_mode_weights_aware_label(path, path[-1], self.context.language), share)
            for path, share in distribution
        ]
        selected_index = next(
            (
                index
                for index, (path, _share) in enumerate(distribution)
                if path == self._selected_path
            ),
            -1,
        )
        _key, subcategory_source, _order = weight_subcategory(self._selected_path)
        self.distribution_title.setText(self.context.t(subcategory_source))
        self.distribution_explanation.setText(
            self.context.t(
                "Chaque poids reste indépendant. La roue montre seulement la part effective obtenue après normalisation du groupe."
            )
        )
        total_share = sum(share for _path, share in distribution)
        raw_total = sum(
            selected_value
            if path == self._selected_path
            else max(0.0, float(get_path_value(self.current, path)))
            for path, _share in distribution
        )
        self.distribution_total.setText(
            (
                self.context.t(
                    "Répartition effective : 100 % · somme des poids : {total} pts"
                ).replace(
                    "{total}",
                    _compact_number(raw_total * 100.0, 1),
                )
                if total_share > 0.999999
                else self.context.t(
                    "Groupe désactivé · tous les poids indépendants sont à 0"
                )
            )
        )
        self.distribution_chart.setAccessibleName(
            self.context.t("Répartition du groupe de pondération")
        )
        self.distribution_chart.set_distribution(
            items, selected_index, self.context.t("effectifs")
        )
        self.distribution_panel.setVisible(True)

    def _commit_editor_value(self, *, show_warning: bool) -> bool:
        if not self._selected_path:
            return True
        try:
            value = self._read_editor_value()
            candidate = copy.deepcopy(self.current)
            set_path_value(candidate, self._selected_path, value)
            validate_scoring_config(candidate)
        except (ValueError, ScoringConfigError, KeyError) as exc:
            if show_warning:
                QMessageBox.warning(
                    self,
                    self.context.t("Valeur refusée"),
                    self.context.t(str(exc)),
                )
            return False
        self.current = candidate
        self._editor_pending = False
        self._editor_original = copy.deepcopy(value)
        current_value = get_path_value(self.current, self._selected_path)
        default_value = get_path_value(self.default, self._selected_path)
        changed = self._path_changed(
            self._selected_path, current_value, default_value
        )
        self._update_distribution_preview()
        self._set_draft_state(changed=changed, pending=False)
        self.apply_button.setEnabled(False)
        self.reset_button.setEnabled(changed)
        self.reset_group_button.setEnabled(
            self._block_changed(self._selected_block_paths(self._selected_path))
        )
        return True

    def apply_value(self) -> bool:
        if not self._commit_editor_value(show_warning=True):
            return False
        self._rebuild_rows()
        return True

    def reset_selected(self) -> None:
        if not self._selected_path:
            return
        set_path_value(
            self.current,
            self._selected_path,
            get_path_value(self.default, self._selected_path),
        )
        validate_scoring_config(self.current)
        self._rebuild_rows()

    def _selected_block_paths(
        self, path: tuple[str, ...] | None
    ) -> tuple[tuple[str, ...], ...]:
        if path is None:
            return ()
        selected_row = next(
            (
                row
                for row in self._all_rows
                if tuple(row["path_tuple"]) == path
            ),
            None,
        )
        if selected_row is None:
            return ()
        subcategory = selected_row["subcategory"]
        return tuple(
            tuple(row["path_tuple"])
            for row in self._all_rows
            if row["subcategory"] == subcategory
        )

    def _block_changed(self, paths: tuple[tuple[str, ...], ...]) -> bool:
        return any(
            get_path_value(self.current, path) != get_path_value(self.default, path)
            for path in paths
        )

    def reset_selected_group(self) -> None:
        paths = self._selected_block_paths(self._selected_path)
        if not paths:
            return
        for path in paths:
            set_path_value(
                self.current,
                path,
                get_path_value(self.default, path),
            )
        validate_scoring_config(self.current)
        self._rebuild_rows()

    def reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            self.context.t("Réinitialiser les pondérations"),
            self.context.t("Rétablir toutes les valeurs par défaut dans l’éditeur ?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.current = copy.deepcopy(self.default)
            self._rebuild_rows()

    def save_profile(self) -> None:
        if self._editor_pending and not self._commit_editor_value(show_warning=True):
            return
        try:
            validate_scoring_config(self.current)
            overrides = build_overrides(self.default, self.current)
            write_json_object(user_scoring_overrides_path(), overrides)
        except (OSError, ScoringConfigError) as exc:
            QMessageBox.warning(self, self.context.t("Profil de pondération invalide"), self.context.t(str(exc)))
            return
        self.active_check.blockSignals(True)
        self.active_check.setChecked(True)
        self.active_check.blockSignals(False)
        self.context.update_lineage(use_custom_scoring=True)
        self._rebuild_rows()
        self._refresh_status()
        QMessageBox.information(self, self.context.t("Pondérations"), self.context.t("Profil enregistré et activé."))

    def _active_changed(self, active: bool) -> None:
        committed_pending = False
        if active and self._editor_pending:
            if not self._commit_editor_value(show_warning=True):
                self.active_check.blockSignals(True)
                self.active_check.setChecked(False)
                self.active_check.blockSignals(False)
                return
            committed_pending = True
        if active:
            try:
                validate_scoring_config(self.current)
            except ScoringConfigError as exc:
                self.active_check.blockSignals(True)
                self.active_check.setChecked(False)
                self.active_check.blockSignals(False)
                QMessageBox.warning(self, self.context.t("Profil de pondération invalide"), self.context.t(str(exc)))
                return
        self.context.update_lineage(use_custom_scoring=active)
        if committed_pending:
            self._rebuild_rows()
        self._refresh_status()

    def _refresh_status(self) -> None:
        overrides = build_overrides(self.default, self.current) if self.default else {}
        count = count_override_leaves(overrides)
        if self.active_check.isChecked():
            text = self.context.t("Profil personnalisé actif · {count} valeur(s) modifiée(s)").replace("{count}", str(count))
        elif count:
            text = self.context.t("Profil par défaut actif · {count} modification(s) enregistrée(s) mais désactivée(s)").replace("{count}", str(count))
        else:
            text = self.context.t("Profil par défaut actif")
        self.status.setText(text)
        self._refresh_priority_status()

    def import_profile(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self, self.context.t("Importer un profil de pondération"), str(Path.home()), "JSON (*.json)"
        )
        if not filename:
            return
        try:
            imported = read_json_object(filename)
            candidate = deep_merge(self.default, imported)
            try:
                validate_scoring_config(imported)
                candidate = imported
            except ScoringConfigError:
                validate_scoring_config(candidate)
        except ScoringConfigError as exc:
            QMessageBox.warning(self, self.context.t("Import impossible"), self.context.t(str(exc)))
            return
        self.current = copy.deepcopy(candidate)
        self._rebuild_rows()

    def export_profile(self) -> None:
        committed_pending = False
        if self._editor_pending:
            if not self._commit_editor_value(show_warning=True):
                return
            committed_pending = True
        if committed_pending:
            self._rebuild_rows()
        filename, _ = QFileDialog.getSaveFileName(
            self,
            self.context.t("Exporter le profil effectif"),
            str(Path(self.context.output_dir).expanduser() / "parent_scoring_profile.json"),
            "JSON (*.json)",
        )
        if not filename:
            return
        try:
            write_json_object(filename, self.current)
        except (OSError, ScoringConfigError) as exc:
            QMessageBox.warning(self, self.context.t("Export impossible"), self.context.t(str(exc)))
            return

    def _priority_changed(self, value: str) -> None:
        self.context.update_lineage(skill_priorities_path=value)
        self._refresh_priority_status()

    def _sync_shared_settings(
        self, _state: LineageContextState | None = None
    ) -> None:
        # lineage_changed can be emitted recursively while a dependent choice
        # is corrected, so always read the latest persisted source of truth.
        state = self.context.lineage_state()
        self.active_check.blockSignals(True)
        self.active_check.setChecked(state.use_custom_scoring)
        self.active_check.blockSignals(False)
        self.priority_picker.set_text(state.skill_priorities_path)
        self._refresh_status()

    def _refresh_priority_status(self) -> None:
        text = self.priority_picker.text()
        if text and Path(text).expanduser().is_file():
            status = self.context.t("Profil personnalisé actif") + f" · {Path(text).name}"
        elif text:
            status = self.context.t("Fichier introuvable") + f" · {text}"
        else:
            status = self.context.t("Profil par défaut actif") + f" · {default_skill_priorities_path().name}"
        self.priority_status.setText(status)

    def create_priority_copy(self) -> None:
        destination = user_skill_priorities_path()
        if destination.exists():
            answer = QMessageBox.question(
                self,
                self.context.t("Copie personnalisée"),
                self.context.t("Écraser la copie personnalisée existante ?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(default_skill_priorities_path(), destination)
            self.priority_picker.set_text(str(destination))
            self._priority_changed(str(destination))
        except OSError as exc:
            QMessageBox.critical(self, self.context.t("Erreur"), str(exc))

    def open_priority(self) -> None:
        path = Path(self.priority_picker.text()).expanduser() if self.priority_picker.text() else default_skill_priorities_path()
        if not path.is_file():
            QMessageBox.warning(self, self.context.t("Fichier introuvable"), str(path))
            return
        open_path(path)

    def reset_priority(self) -> None:
        self.priority_picker.set_text("")
        self._priority_changed("")

    def retranslate(self) -> None:
        t = self.context.t
        self.header.set_text(
            t("Pondérations"),
            t("Comprends l’effet de chaque réglage, ajuste-le avec un contrôle adapté, puis enregistre uniquement tes différences."),
        )
        self.active_check.setText(t("Utiliser mes pondérations personnalisées"))
        self.import_button.setText(t("Importer…"))
        self.export_button.setText(t("Exporter l’effectif…"))
        self.save_button.setText(t("Enregistrer et activer"))
        self.search.setPlaceholderText(t("Rechercher un réglage…"))
        self.category_filter_label.setText(t("Domaine de calcul"))
        self.category_combo.setToolTip(
            t("Choisis un domaine ; les réglages restent séparés par bloc de calcul dans l’arborescence.")
        )
        self.changed_only.setText(t("Modifiés uniquement"))
        self.show_advanced.setText(t("Afficher les réglages avancés"))
        self.reset_all_button.setText(t("Tout remettre par défaut"))
        self.settings_title.setText(t("Réglages par bloc"))
        self.hover_hint.setText(
            t("Déplie un bloc de calcul, puis survole un réglage pour son résumé.")
        )
        self.empty_label.setText(t("Aucun réglage sélectionné."))
        self.current_label.setText(t("Valeur active"))
        self.default_label.setText(t("Valeur par défaut"))
        self.apply_button.setText(t("Appliquer"))
        self.reset_button.setText(t("Rétablir la valeur"))
        self.reset_group_button.setText(t("Rétablir le bloc"))
        self.reset_group_button.setToolTip(
            t("Rétablit tous les réglages du bloc de calcul sélectionné.")
        )
        self.save_hint.setText(
            t("Le brouillon reste local jusqu’à « Enregistrer et activer ».")
        )
        self.priorities.set_title(t("Priorités individuelles des White Skills · avancé"))
        self.priority_help.setText(
            t(
                "Même source que dans Recherche de lignées, pour les calculs locaux et uma.moe. Un JSON partiel est fusionné avec default_skill_priorities.json avant chaque calcul."
            )
        )
        self.priority_picker.dialog_title = t("Choisir un profil de priorités white")
        self.priority_picker.file_filter = f"JSON (*.json);;{t('Tous les fichiers')} (*)"
        self.priority_picker.set_button_text(t("Parcourir…"))
        self.priority_picker.setToolTip(
            t(
                "Ce fichier règle la valeur de chaque white skill par surface, distance et style. Un profil partiel est accepté : il est fusionné avec default_skill_priorities.json avant chaque calcul."
            )
        )
        self.create_priority_button.setText(t("Créer une copie modifiable"))
        self.open_priority_button.setText(t("Ouvrir"))
        self.reset_priority_button.setText(t("Revenir au défaut"))
        self._rebuild_rows()
        self._refresh_status()

    def set_busy(self, _busy: bool) -> None:
        # This page only performs short local file operations on the UI thread.
        return

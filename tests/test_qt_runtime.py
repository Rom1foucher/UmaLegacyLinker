from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # Source-only backend test environments do not install Qt.
    QApplication = None  # type: ignore[assignment]


@unittest.skipUnless(QApplication is not None, "PySide6 is not installed")
class QtRuntimeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        assert QApplication is not None
        cls.application = QApplication.instance() or QApplication([])

    def test_every_page_constructs_and_retranslates(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.main_window import MainWindow
        from ui_qt.theme import application_stylesheet

        self.application.setStyle("Fusion")
        self.application.setStyleSheet(application_stylesheet())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SettingsStore(root / "config.json")
            store.update({"output_dir": str(root / "output"), "ui_language": "fr"})
            window = MainWindow(AppContext(store))
            window.show()
            self.application.processEvents()
            self.assertEqual(
                set(window._pages),
                {"home", "data", "search", "transfer", "weights", "tools"},
            )
            for language in ("fr", "en"):
                window.context.set_language(language)
                for page in window._nav_order:
                    window.show_page(page)
                    self.application.processEvents()
                    self.assertIs(window.stack.currentWidget(), window._pages[page])
            window.close()

    def test_result_panes_do_not_refresh_before_the_detail_browser_exists(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.pages_optimizer import ResultPane

        errors: list[BaseException] = []
        previous_hook = sys.excepthook
        sys.excepthook = lambda _kind, value, _traceback: errors.append(value)
        panes = []
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                context = AppContext(SettingsStore(Path(temp_dir) / "config.json"))
                for kind in ("pair", "branch", "future"):
                    pane = ResultPane(kind, context)
                    pane.show()
                    panes.append(pane)
                self.application.processEvents()
                self.assertTrue(all(pane.detail.minimumWidth() >= 520 for pane in panes))
                self.assertEqual(errors, [])
        finally:
            for pane in panes:
                _dispose_widget(pane, self.application)
            sys.excepthook = previous_hook

    def test_online_parent_results_expose_lineage_planner_export(self) -> None:
        from unittest.mock import patch

        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.pages_online import OnlineResultsPane

        with tempfile.TemporaryDirectory() as temp_dir:
            context = AppContext(
                SettingsStore(Path(temp_dir) / "config.json")
            )
            pane = OnlineResultsPane(context)
            pane.set_payload(
                {
                    "ace": {"card_id": 100101},
                    "results": [
                        {
                            "fixed_parent": {"card_id": 100201},
                            "candidate": {"card_id": 100301},
                        }
                    ],
                },
                "parent",
            )
            self.application.processEvents()
            self.assertTrue(pane.export_button.isEnabled())
            self.assertTrue(pane.copy_export_button.isEnabled())

            expected = {
                "version": 1,
                "type": "lineage-planner",
                "payload": [],
            }
            with patch(
                "ui_qt.pages_online.build_lineage_planner_export",
                return_value=expected,
            ) as build:
                pane.copy_selected_pair_export()
            self.assertEqual(
                json.loads(QApplication.clipboard().text()),
                expected,
            )
            build.assert_called_once()

            pane.set_payload(
                {
                    "target_parent": {"card_id": 100401},
                    "results": [
                        {
                            "fixed_grandparent": {"card_id": 100501},
                            "candidate": {"card_id": 100601},
                        }
                    ],
                },
                "grandparent",
            )
            self.application.processEvents()
            self.assertFalse(pane.export_button.isEnabled())
            self.assertFalse(pane.copy_export_button.isEnabled())
            _dispose_widget(pane, self.application)

    def test_searchable_combo_resolves_text_without_stale_item_data(self) -> None:
        from ui_qt.components import SearchableComboBox

        combo = SearchableComboBox()
        combo.addItem("Gold Ship — Original", 101)
        combo.addItem("Mejiro McQueen — Original", 202)
        combo.addItem("Mejiro McQueen — Summer", 203)
        combo.setCurrentIndex(0)

        assert combo.lineEdit() is not None
        combo.lineEdit().setText("McQueen")
        combo.lineEdit().textEdited.emit("McQueen")
        self.assertEqual(combo.currentIndex(), -1)
        self.assertIsNone(combo.currentData())
        self.assertFalse(combo.resolve_current_text())

        combo.lineEdit().setText("summer")
        combo.lineEdit().textEdited.emit("summer")
        self.assertTrue(combo.resolve_current_text())
        self.assertEqual(combo.currentData(), 203)

        combo._completion_activated("MEJIRO MCQUEEN — ORIGINAL")
        self.assertEqual(combo.currentData(), 202)

    def test_shared_race_editor_applies_clears_and_synchronizes_presets(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.lineage_settings import LineageRaceEditor

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            presets = root / "courses.json"
            presets.write_text(
                json.dumps(
                    {
                        "courses": {
                            "full": {
                                "label": "Full preset",
                                "profile": {
                                    "surface": "turf",
                                    "distance": "medium",
                                },
                                "race": {"racecourse": "Kyoto"},
                                "conditions": {
                                    "track_id": 10008,
                                    "rotation": 1,
                                    "season": 3,
                                    "weather": 1,
                                    "ground_condition": 1,
                                },
                            },
                            "partial": {
                                "label": "Partial preset",
                                "profile": {
                                    "surface": "dirt",
                                    "distance": "mile",
                                },
                                "conditions": {"rotation": 2},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            store = SettingsStore(root / "config.json")
            store.update({"course_overrides_path": str(presets)})
            context = AppContext(store)
            first = LineageRaceEditor(context)
            second = LineageRaceEditor(context)
            tracks = [
                SimpleNamespace(
                    name="Kyoto",
                    display_name="Kyoto (10008)",
                    track_id=10008,
                )
            ]
            first.course_combo.setCurrentIndex(
                first.course_combo.findData("full")
            )
            state = context.lineage_state()
            self.assertEqual(state.course_key, "full")
            self.assertEqual((state.surface, state.distance), ("turf", "medium"))
            # A preset selected before the MDB lists load must not lose its
            # explicit track identifier.
            self.assertEqual(state.track_id, 10008)
            first.set_track_options(tracks)
            second.set_track_options(tracks)
            self.assertEqual(state.season, "Automne")
            self.assertEqual(second.course_combo.currentData(), "full")
            self.assertEqual(second.track_combo.currentData(), 10008)

            style_index = first.style_combo.findData("end_closer")
            first.style_combo.setCurrentIndex(style_index)
            first.style_combo.activated.emit(style_index)
            self.assertEqual(context.lineage_state().course_key, "full")

            surface_index = first.surface_combo.findData("dirt")
            first.surface_combo.setCurrentIndex(surface_index)
            first.surface_combo.activated.emit(surface_index)
            self.assertEqual(context.lineage_state().course_key, "")
            self.assertEqual(second.course_combo.currentIndex(), 0)

            first.course_combo.setCurrentIndex(
                first.course_combo.findData("full")
            )
            first.course_combo.setCurrentIndex(
                first.course_combo.findData("partial")
            )
            state = context.lineage_state()
            self.assertEqual(state.course_key, "partial")
            self.assertEqual((state.surface, state.distance), ("dirt", "mile"))
            self.assertEqual(state.rotation, "Gauche")
            self.assertEqual(state.season, "Non précisé")
            self.assertEqual(state.weather, "Non précisé")
            self.assertEqual(state.ground_condition, "Non précisé")
            self.assertEqual(state.track_id, 0)

            second.course_combo.setCurrentIndex(0)
            self.assertEqual(context.lineage_state().course_key, "")
            self.assertEqual(first.course_combo.currentIndex(), 0)
            self.assertEqual(store.get("optimizer_course_key"), "")

            _dispose_widget(first, self.application)
            _dispose_widget(second, self.application)

    def test_search_workspace_uses_one_live_context_for_every_search(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.pages_search import SearchPage

        with tempfile.TemporaryDirectory() as temp_dir:
            context = AppContext(
                SettingsStore(Path(temp_dir) / "config.json")
            )
            search = SearchPage(context)
            options = (
                ("Ace — Costume", 101, 1),
                ("Parent — Costume", 202, 2),
                ("Other — Costume", 303, 3),
            )
            search._card_to_chara = {
                card_id: chara_id
                for _label, card_id, chara_id in options
            }
            for combo in (search.ace_combo, search.target_combo):
                combo.blockSignals(True)
                combo.clear()
                for label, card_id, _chara_id in options:
                    combo.addItem(label, card_id)
                combo.blockSignals(False)

            search.ace_combo.setCurrentIndex(search.ace_combo.findData(101))
            search.target_combo.setCurrentIndex(search.target_combo.findData(202))
            self.assertEqual(context.lineage_state().ace_card_id, 101)
            self.assertEqual(context.lineage_state().future_parent_card_id, 202)

            # The single shared editor still enforces the domain rule.
            search.target_combo.setCurrentIndex(search.target_combo.findData(101))
            search._ensure_distinct_parent()
            search._lineage_selection_changed()
            self.assertEqual(context.lineage_state().future_parent_card_id, 202)
            self.assertEqual(search.target_combo.currentData(), 202)

            search.top_spin.setValue(77)
            self.assertEqual(context.lineage_state().top_n, 77)

            dirt_index = search.race_editor.surface_combo.findData("dirt")
            search.race_editor.surface_combo.setCurrentIndex(dirt_index)
            search.race_editor.surface_combo.activated.emit(dirt_index)
            self.assertEqual(context.store.get("optimizer_surface"), "dirt")

            self.assertEqual(
                search._optimization_request("pairs").search_kind, "pairs"
            )
            self.assertEqual(
                search._optimization_request("branches").search_kind, "branches"
            )
            self.assertEqual(
                search._optimization_request("future").search_kind, "future"
            )

            _dispose_widget(search, self.application)

    def test_search_workspace_loads_the_latest_remote_result_too(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.pages_search import SearchPage

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "output"
            output.mkdir()
            (output / "uma_moe_parent_pairs.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "profile": {
                                "surface": "turf",
                                "distance": "medium",
                                "style": "pace_chaser",
                            }
                        },
                        "ace": {"card_id": 101, "card_name": "Ace"},
                        "results": [],
                    }
                ),
                encoding="utf-8",
            )
            store = SettingsStore(root / "config.json")
            store.update({"output_dir": str(output)})
            search = SearchPage(AppContext(store))
            search._initial_refresh_timer.stop()
            search._initial_result_timer.stop()
            search.load_latest(show_errors=True)

            self.assertEqual(search._active_result_kind, "uma.moe:online_parent")
            self.assertIs(search.result_stack.currentWidget(), search.online_results)
            self.assertEqual(search.online_results.mode, "parent")
            _dispose_widget(search, self.application)

    def test_uma_moe_integration_is_persisted_by_settings_context(self) -> None:
        from unittest.mock import patch

        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            with patch("ui_qt.context.resolve_api_key", return_value=""):
                context = AppContext(store)
            changes: list[bool] = []
            context.integration_changed.connect(lambda: changes.append(True))
            with patch("ui_qt.context.save_api_key") as save_key:
                context.update_uma_moe_integration(
                    api_base=" https://example.test/api ",
                    api_key=" secret-token ",
                    remember_api_key=True,
                )

            self.assertEqual(context.uma_moe_api_base, "https://example.test/api")
            self.assertEqual(context.uma_moe_api_key, "secret-token")
            self.assertTrue(context.uma_moe_remember_api_key)
            self.assertEqual(store.get("uma_moe_base"), "https://example.test/api")
            self.assertEqual(store.get("uma_moe_remember_api_key"), "1")
            save_key.assert_called_once()
            self.assertEqual(save_key.call_args.args[1], "secret-token")
            self.assertEqual(changes, [True])

    def test_weights_and_lineage_share_scoring_sources_bidirectionally(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.lineage_settings import LineageRaceEditor
        from ui_qt.pages_weights import WeightsPage

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_profile = root / "first-priorities.json"
            second_profile = root / "second-priorities.json"
            first_profile.write_text("{}\n", encoding="utf-8")
            second_profile.write_text("{}\n", encoding="utf-8")
            context = AppContext(SettingsStore(root / "config.json"))
            lineage = LineageRaceEditor(context)
            weights = WeightsPage(context)

            weights.priority_picker.set_text(str(first_profile))
            weights.priority_picker.path_changed.emit(str(first_profile))
            self.assertEqual(
                lineage.priority_picker.text(), str(first_profile)
            )

            lineage.priority_picker.set_text(str(second_profile))
            lineage.priority_picker.path_changed.emit(str(second_profile))
            self.assertEqual(
                weights.priority_picker.text(), str(second_profile)
            )
            self.assertEqual(
                context.lineage_state().skill_priorities_path,
                str(second_profile),
            )

            weights.active_check.setChecked(True)
            self.assertTrue(lineage.custom_scoring.isChecked())
            lineage.custom_scoring.setChecked(False)
            self.assertFalse(weights.active_check.isChecked())

            _dispose_widget(lineage, self.application)
            _dispose_widget(weights, self.application)

    def test_combo_popups_keep_dark_readable_palettes(self) -> None:
        from PySide6.QtGui import QPalette

        from ui_qt.components import SearchableComboBox, ThemedComboBox
        from ui_qt.layout_audit import _dispose_widget
        from ui_qt.theme import COLORS

        for combo in (ThemedComboBox(), SearchableComboBox()):
            views = [combo.view()]
            if isinstance(combo, SearchableComboBox):
                views.append(combo.completer().popup())
            for view in views:
                palette = view.palette()
                self.assertEqual(
                    palette.color(QPalette.ColorRole.Base).name(),
                    COLORS["surface_alt"],
                )
                self.assertEqual(
                    palette.color(QPalette.ColorRole.Text).name(),
                    COLORS["text"],
                )
                self.assertNotEqual(
                    palette.color(QPalette.ColorRole.Base),
                    palette.color(QPalette.ColorRole.Text),
                )
            _dispose_widget(combo, self.application)

    def test_distribution_chart_renders_at_editor_width(self) -> None:
        from ui_qt.distribution_chart import DistributionDonut

        chart = DistributionDonut()
        chart.set_distribution(
            [
                ("Distance S", 0.29),
                ("Other Pink Sparks", 0.07),
                ("White Skills", 0.35),
                ("Race Sparks", 0.04),
                ("Blue Sparks", 0.20),
                ("Unique", 0.05),
            ],
            0,
            "of group",
        )
        chart.resize(310, chart.sizeHint().height())
        chart.show()
        self.application.processEvents()
        image = chart.grab().toImage()
        self.assertFalse(image.isNull())
        self.assertIn("Distance S", chart.toolTip())
        chart.close()

    def test_layout_audit_disposes_top_levels_immediately(self) -> None:
        from PySide6.QtWidgets import QWidget
        from shiboken6 import isValid

        from ui_qt.layout_audit import _dispose_widget

        widget = QWidget()
        widget.show()
        self.application.processEvents()
        self.assertTrue(isValid(widget))
        _dispose_widget(widget, self.application)
        self.assertFalse(isValid(widget))

    def test_layout_audit_uses_qt_control_content_rects(self) -> None:
        from PySide6.QtWidgets import QLabel, QPushButton

        from ui_qt.layout_audit import _button_text_width, _text_overflow
        from ui_qt.theme import application_stylesheet

        self.application.setStyle("Fusion")
        self.application.setStyleSheet(application_stylesheet())

        label = QLabel("Exactly fitted label")
        label.resize(320, 40)
        label.show()

        button = QPushButton("Exactly fitted button")
        button.resize(320, button.sizeHint().height())
        button.show()
        self.application.processEvents()
        label_chrome_width = label.width() - label.contentsRect().width()
        label_text_width = label.fontMetrics().horizontalAdvance(label.text())
        label.resize(label_text_width + label_chrome_width, label.height())
        chrome_width = button.width() - _button_text_width(button)
        text_width = button.fontMetrics().horizontalAdvance(button.text())
        button.resize(text_width + chrome_width, button.height())
        self.application.processEvents()

        self.assertFalse(_text_overflow(label))
        self.assertFalse(_text_overflow(button))

        label.resize(label.width() - 1, label.height())
        button.resize(button.width() - 1, button.height())
        self.assertTrue(_text_overflow(label))
        self.assertTrue(_text_overflow(button))
        label.close()
        button.close()

    def test_narrow_layouts_fit_the_audited_content_width(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.layout_audit import _dispose_widget, _text_overflow, audit_window
        from ui_qt.main_window import MainWindow
        from ui_qt.theme import application_stylesheet

        self.application.setStyle("Fusion")
        self.application.setStyleSheet(application_stylesheet())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = SettingsStore(root / "config.json")
            store.update({"output_dir": str(root / "output"), "ui_language": "fr"})
            window = MainWindow(AppContext(store))
            window.resize(1120, 720)
            window.show()
            self.application.processEvents()
            try:
                for language in ("fr", "en"):
                    window.context.set_language(language)
                    window.show_page("data")
                    self.application.processEvents()
                    self.assertFalse(
                        _text_overflow(window._pages["data"].extractor_label)
                    )

                    weights = window._pages["weights"]
                    window.show_page("weights")
                    self.application.processEvents()
                    self.assertFalse(_text_overflow(weights.changed_only))
                    self.assertFalse(_text_overflow(weights.show_advanced))

                    window.show_page("search")
                    self.application.processEvents()
                    issues = audit_window(window)
                    self.assertFalse(
                        any(
                            "overflow" in issue
                            for issue in issues
                        ),
                        f"{language}/search: {issues}",
                    )

                    transfer = window._pages["transfer"]
                    window.show_page("transfer")
                    for width in (1120, 1366):
                        window.resize(width, 720 if width == 1120 else 768)
                        self.application.processEvents()
                        issues = audit_window(window)
                        self.assertFalse(
                            any("overflow" in issue for issue in issues),
                            f"{language}/transfer/{width}: {issues}",
                        )
                        for control in (
                            transfer.upcoming_cm_check,
                            transfer.run_button,
                            transfer.load_button,
                            transfer.open_button,
                        ):
                            self.assertFalse(_text_overflow(control))
            finally:
                _dispose_widget(window, self.application)

    def test_lineage_dialog_renders_complete_pair_without_network(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.lineage_view import LineageDialog

        def member(card_id: int, name: str) -> dict[str, object]:
            return {
                "card_id": card_id,
                "uma_name": name,
                "card_name": f"{name} costume",
                "sparks": [
                    {"name": "Speed", "stars": 3, "type": "blue_stat"},
                    {"name": "Medium", "stars": 2, "type": "red_aptitude"},
                    {
                        "name": "Corner Adept",
                        "stars": 2,
                        "type": "white_skill",
                        "skill_id": 10011,
                    },
                ],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            store.update({"online_images": "0", "ui_language": "en"})
            context = AppContext(store)
            preview = {
                "p1": member(100701, "Gold Ship"),
                "p2": member(101301, "Mejiro McQueen"),
                "p1-1": member(100101, "Special Week"),
                "p1-2": member(100201, "Silence Suzuka"),
                "p2-1": member(100301, "Tokai Teio"),
                "p2-2": member(100401, "Maruzensky"),
            }
            dialog = LineageDialog(
                context,
                {"card_id": 103101, "uma_name": "Ace", "card_name": "Ace costume"},
                {
                    "score": 88.5,
                    "parent_1": preview["p1"],
                    "parent_2": preview["p2"],
                    "lineage_preview": preview,
                    "affinity": {
                        "total": 160,
                        "inheritance_affinities": {
                            "values": {
                                "parent_1": 160,
                                "parent_2": 150,
                            }
                        },
                    },
                    "component_details": {
                        "white_skill": {
                            "inspiration_event_count": 2,
                            "top_skills": [
                                {
                                    "name": "Corner Adept",
                                    "catalog_key": "corner_adept",
                                    "profile_weight": 0.8,
                                    "contribution": 0.42,
                                }
                            ],
                            "factors": [
                                {
                                    "role": "parent_1",
                                    "source_type": "white_skill",
                                    "source_factor_name": "Corner Adept",
                                    "catalog_key": "corner_adept",
                                    "stars": 2,
                                    "proc_probability_over_run": 0.246576,
                                }
                            ],
                        }
                    },
                    "distance_s_summary": {"probability_reach_s": 0.55},
                },
                details_html="<p>Diagnostics</p>",
            )
            dialog.resize(1120, 720)
            dialog.show()
            self.application.processEvents()
            self.assertFalse(dialog.online_toggle.isChecked())
            self.assertEqual(len(dialog.tree.nodes), 7)
            self.assertEqual(dialog.tabs.count(), 2)
            white = next(
                factor
                for factor in dialog.tree.nodes["p1"]["sparks"]
                if factor["type"] == "white_skill"
            )
            self.assertAlmostEqual(white["proc_probability_over_run"], 0.246576)
            self.assertTrue(white["is_score_priority"])
            self.assertIn("Inspiration Events", dialog.spark_legend.text())
            self.assertFalse(dialog.grab().toImage().isNull())
            self.assertIn("GameTora", dialog.attribution.text())
            dialog.close()

    def test_lineage_dialog_adds_the_g1_affinity_calendar(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.lineage_view import LineageDialog

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            store.update({"online_images": "0", "ui_language": "en"})
            dialog = LineageDialog(
                AppContext(store),
                {"card_id": 103101, "card_name": "Ace costume"},
                {
                    "score": 91.0,
                    "parent_1": {"card_name": "Parent 1", "sparks": []},
                    "parent_2": {"card_name": "Parent 2", "sparks": []},
                    "race_affinity_plan": {
                        "shared_race_bonus": 6,
                        "one_side_race_bonus": 3,
                        "races": [
                            {
                                "race_id": 1022,
                                "name": "Kawasaki Kinen",
                                "shared": True,
                                "affinity_bonus": 6,
                                "sources": ["Parent 1", "Parent 2"],
                                "schedule_slots": [
                                    {"year": 2, "month": 2, "half": 1},
                                    {"year": 3, "month": 2, "half": 1}
                                ],
                            },
                            {
                                "race_id": 1033,
                                "name": "Oka Sho",
                                "shared": False,
                                "affinity_bonus": 3,
                                "sources": ["Parent 1"],
                                "schedule_slots": [
                                    {"year": 2, "month": 4, "half": 1}
                                ],
                            },
                        ],
                    },
                    "affinity": {"total": 160},
                    "distance_s_summary": {"probability_reach_s": 0.55},
                },
            )
            dialog.resize(1120, 720)
            dialog.show()
            self.application.processEvents()
            self.assertEqual(dialog.tabs.count(), 3)
            self.assertIsNotNone(dialog.calendar)
            self.assertEqual(dialog.calendar.width(), dialog.calendar.BASE_WIDTH)
            self.assertEqual(
                dialog.calendar.minimumSize(),
                dialog.calendar.maximumSize(),
            )
            first_hint = dialog.calendar.sizeHint()
            for width in (900, 1800, 1120, 1360):
                dialog.calendar.resize(width, dialog.calendar.height())
                self.application.processEvents()
                self.assertEqual(dialog.calendar.sizeHint(), first_hint)
            self.assertIn("+6", dialog.planning_legend.text())
            self.assertIn("+3", dialog.planning_legend.text())
            self.assertEqual(
                dialog.calendar._race_urls[0],
                "https://media.gametora.com/umamusume/races/banners/en/1022.png",
            )
            scheduled, unscheduled = dialog.calendar._calendar_entries()
            self.assertEqual(scheduled[(2, 2, 1)][0][1]["affinity_bonus"], 6)
            self.assertNotIn((3, 2, 1), scheduled)
            self.assertEqual(
                sum(len(items) for items in scheduled.values()),
                2,
            )
            self.assertFalse(unscheduled)
            self.assertFalse(dialog.calendar.grab().toImage().isNull())
            dialog.close()

    def test_lineage_planning_switches_to_trackblazer_without_recomputing(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.lineage_view import LineageDialog

        slot = {"year": 2, "month": 5, "half": 2}
        objective = {
            "race_id": 2002,
            "name": "Mandatory Trial",
            "affinity_bonus": 0,
            "mandatory_objective": True,
            "objective_only": True,
            "planned_slot": slot,
            "planning_status": "scheduled",
        }
        blocked_g1 = {
            "race_id": 1001,
            "name": "Affinity Cup",
            "affinity_bonus": 6,
            "shared": True,
            "planned_slot": None,
            "planning_status": "objective_conflict",
        }
        trackblazer_g1 = {
            **blocked_g1,
            "planned_slot": slot,
            "planning_status": "scheduled",
        }
        plan = {
            "shared_race_bonus": 6,
            "one_side_race_bonus": 3,
            "objective_race_count": 1,
            "races": [blocked_g1, objective],
            "schedule_variants": {
                "standard": {
                    "mode": "standard",
                    "races": [blocked_g1, objective],
                    "optimal_bonus": 0,
                    "optimal_affinity_race_count": 0,
                    "scheduled_objective_race_count": 1,
                    "streaks": {"max_consecutive": 1},
                },
                "trackblazer": {
                    "mode": "trackblazer",
                    "races": [trackblazer_g1],
                    "optimal_bonus": 6,
                    "optimal_affinity_race_count": 1,
                    "scheduled_objective_race_count": 0,
                    "streaks": {"max_consecutive": 1},
                },
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            store.update({"online_images": "0", "ui_language": "en"})
            dialog = LineageDialog(
                AppContext(store),
                {"card_id": 103101, "card_name": "Target"},
                {
                    "score": 90,
                    "parent_1": {"card_name": "Local", "sparks": []},
                    "parent_2": {"card_name": "Remote", "sparks": []},
                    "race_affinity_plan": plan,
                    "affinity": {"total": 150},
                },
            )
            self.assertIsNotNone(dialog.trackblazer_toggle)
            self.assertTrue(dialog.trackblazer_toggle.isEnabled())
            self.assertEqual(dialog.calendar.plan["mode"], "standard")
            self.assertIn("0 affinity", dialog.planning_legend.text())
            dialog.trackblazer_toggle.setChecked(True)
            self.application.processEvents()
            self.assertEqual(dialog.calendar.plan["mode"], "trackblazer")
            self.assertIn("objectives ignored", dialog.planning_legend.text())
            scheduled, excluded = dialog.calendar._calendar_entries()
            self.assertEqual(scheduled[(2, 5, 2)][0][1]["name"], "Affinity Cup")
            self.assertFalse(excluded)
            dialog.close()

    def test_grandparent_dialog_uses_target_parent_as_root(self) -> None:
        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.lineage_view import LineageDialog

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            store.update({"online_images": "0", "ui_language": "en"})
            dialog = LineageDialog(
                AppContext(store),
                {"card_id": 100101, "card_name": "Parent to produce"},
                {
                    "score": 74.2,
                    "fixed_grandparent": {"card_name": "Local GP"},
                    "candidate": {"card_name": "Remote GP"},
                    "lineage_preview": {
                        "p1": {"card_name": "Local GP", "sparks": []},
                        "p2": {"card_name": "Remote GP", "sparks": []},
                        "p1-1": {"card_name": "Local ancestor 1", "sparks": []},
                        "p1-2": {"card_name": "Local ancestor 2", "sparks": []},
                        "p2-1": {"card_name": "Remote ancestor 1", "sparks": []},
                        "p2-2": {"card_name": "Remote ancestor 2", "sparks": []},
                    },
                    "final_parent_affinity": {
                        "potential_total": 168,
                        "common_g1_count": 7,
                    },
                },
                mode="online_grandparent",
            )
            dialog.resize(1120, 720)
            dialog.show()
            self.application.processEvents()
            self.assertEqual(
                dialog.tree.nodes["target"]["card_name"], "Parent to produce"
            )
            self.assertEqual(dialog.tree.nodes["p1"]["card_name"], "Local GP")
            self.assertEqual(dialog.tree.nodes["p2"]["card_name"], "Remote GP")
            self.assertEqual(dialog.title_label.text(), "Grandparent pair")
            self.assertEqual(dialog.distance_badge.value.text(), "7")
            self.assertFalse(dialog.distance_badge.rank_glyph.isVisible())
            self.assertFalse(dialog.grab().toImage().isNull())
            dialog.close()

    def test_weight_page_uses_categories_and_typed_controls(self) -> None:
        from PySide6.QtCore import Qt

        from ui_qt.context import AppContext
        from ui_qt.core import SettingsStore
        from ui_qt.pages_weights import WeightsPage
        from ui_qt.weight_controls import relative_group_paths, relative_group_shares

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            page = WeightsPage(AppContext(store))
            headers = [page.tree.headerItem().text(index) for index in range(3)]
            self.assertNotIn("Chemin JSON", headers)
            self.assertNotIn("JSON path", headers)
            self.assertEqual(page.tree.columnCount(), 3)
            self.assertGreater(page.category_combo.count(), 3)
            page.category_combo.setCurrentIndex(
                page.category_combo.findData("global")
            )
            self.application.processEvents()
            self.assertEqual(page.tree.topLevelItemCount(), 3)
            percentage_row = next(
                row
                for row in page._all_rows
                if row["path_tuple"][:2] == ("mode_weights", "parent_pair")
            )
            page._show_selection(percentage_row)
            self.assertEqual(page._editor_kind, "relative_weight")
            self.assertFalse(page.distribution_panel.isHidden())
            self.assertEqual(len(page._relative_paths), 7)
            self.assertTrue(page.editor_summary.text())
            self.assertTrue(page.impact_text.text())
            self.assertTrue(page.percent_low.text())
            self.assertTrue(page.percent_high.text())
            tooltip = page._tree_items[percentage_row["path_tuple"]].toolTip(0)
            self.assertTrue(tooltip)
            group_paths = relative_group_paths(
                page.current, percentage_row["path_tuple"]
            )
            before = {
                path: page.current[path[0]][path[1]][path[2]]
                for path in group_paths
            }
            page.percent_spin.setValue(37.5)
            self.assertEqual(page.percent_slider.value(), 375)
            self.assertAlmostEqual(float(page._read_editor_value()), 0.375)
            self.assertTrue(page.apply_button.isEnabled())
            self.assertEqual(page.draft_state.text(), "Modification à appliquer")
            page.search.setText(str(percentage_row["label"]))
            self.application.processEvents()
            self.assertAlmostEqual(page.percent_spin.value(), 37.5)
            self.assertTrue(page.apply_button.isEnabled())
            self.assertTrue(page.apply_value())
            after = {
                path: page.current[path[0]][path[1]][path[2]]
                for path in group_paths
            }
            selected_path = percentage_row["path_tuple"]
            self.assertAlmostEqual(after[selected_path], 0.375)
            self.assertEqual(
                {path: value for path, value in after.items() if path != selected_path},
                {path: value for path, value in before.items() if path != selected_path},
            )
            shares = dict(
                relative_group_shares(page.current, selected_path)
            )
            self.assertAlmostEqual(sum(shares.values()), 1.0)
            self.assertAlmostEqual(
                shares[selected_path], after[selected_path] / sum(after.values())
            )
            other_path = next(path for path in group_paths if path != selected_path)
            other_custom = after[other_path] * 1.25
            page.current[other_path[0]][other_path[1]][other_path[2]] = other_custom
            page._show_selection(percentage_row)
            page.reset_selected()
            self.assertEqual(
                page.current[selected_path[0]][selected_path[1]][selected_path[2]],
                page.default[selected_path[0]][selected_path[1]][selected_path[2]],
            )
            self.assertAlmostEqual(
                page.current[other_path[0]][other_path[1]][other_path[2]],
                other_custom,
            )
            page.reset_selected_group()
            self.assertEqual(
                page.current[other_path[0]][other_path[1]][other_path[2]],
                page.default[other_path[0]][other_path[1]][other_path[2]],
            )
            multiplier_row = next(
                row
                for row in page._all_rows
                if row["path_tuple"]
                == ("blue_stat_weights_by_distance", "long", "Stamina")
            )
            page._show_selection(multiplier_row)
            self.assertEqual(page._editor_kind, "multiplier")
            self.assertEqual(page.percent_spin.prefix(), "×")
            self.assertTrue(page.distribution_panel.isHidden())
            probability_row = next(
                row
                for row in page._all_rows
                if row["path_tuple"]
                == ("white_inheritance", "base_proc_rates", "3")
            )
            page._show_selection(probability_row)
            self.assertEqual(page._editor_kind, "percentage")
            self.assertEqual(page.type_badge.text(), "Probabilité")
            boolean_row = next(
                row
                for row in page._all_rows
                if row["path_tuple"]
                == ("transfer_helper", "include_course_presets")
            )
            page._show_selection(boolean_row)
            self.assertEqual(page._editor_kind, "bool")
            page.bool_edit.setChecked(False)
            self.assertIs(page._read_editor_value(), False)
            page.close()


if __name__ == "__main__":
    unittest.main()

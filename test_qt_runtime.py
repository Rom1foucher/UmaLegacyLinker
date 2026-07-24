from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


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
                {"home", "data", "optimizer", "online", "transfer", "weights", "tools"},
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
                pane.close()
            sys.excepthook = previous_hook

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

    def test_distribution_chart_renders_at_editor_width(self) -> None:
        from ui_qt.distribution_chart import DistributionDonut

        chart = DistributionDonut()
        chart.set_distribution(
            [
                ("Distance S", 0.29),
                ("Other Pink Sparks", 0.07),
                ("White Skills", 0.35),
                ("Race/Scenario", 0.04),
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
        from ui_qt.weight_controls import relative_group_shares

        with tempfile.TemporaryDirectory() as temp_dir:
            store = SettingsStore(Path(temp_dir) / "config.json")
            page = WeightsPage(AppContext(store))
            headers = [
                page.model.headerData(index, Qt.Orientation.Horizontal)
                for index in range(page.model.columnCount())
            ]
            self.assertNotIn("Chemin JSON", headers)
            self.assertNotIn("JSON path", headers)
            self.assertEqual(page.model.columnCount(), 3)
            self.assertGreater(page.category_combo.count(), 3)
            page.category_combo.setCurrentIndex(
                page.category_combo.findData("global")
            )
            self.application.processEvents()
            self.assertGreater(page.subcategory_combo.count(), 3)
            percentage_row = next(
                row
                for row in page._all_rows
                if row["path_tuple"][:2] == ("mode_weights", "parent_pair")
            )
            page._show_selection(percentage_row)
            self.assertEqual(page._editor_kind, "relative_share")
            self.assertFalse(page.distribution_panel.isHidden())
            self.assertEqual(len(page._relative_paths), 6)
            self.assertTrue(page.editor_summary.text())
            self.assertTrue(page.impact_text.text())
            self.assertTrue(page.percent_low.text())
            self.assertTrue(page.percent_high.text())
            tooltip = page.model.data(page.model.index(0, 0), Qt.ItemDataRole.ToolTipRole)
            self.assertTrue(tooltip)
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
            shares = dict(
                relative_group_shares(page.current, percentage_row["path_tuple"])
            )
            self.assertAlmostEqual(sum(shares.values()), 1.0)
            self.assertAlmostEqual(shares[percentage_row["path_tuple"]], 0.375)
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

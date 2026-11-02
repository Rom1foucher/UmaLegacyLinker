from __future__ import annotations

import unittest
from pathlib import Path

from uma_legacy_linker.i18n import translate_text
from uma_legacy_linker.application import OnlineSearchRequest, materialize_online_search_options


PROJECT_DIR = Path(__file__).resolve().parents[1]


class DataPageHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (PROJECT_DIR / "ui_qt" / "pages_home_data.py").read_text(
            encoding="utf-8"
        )

    def test_extraction_is_the_primary_first_action(self) -> None:
        self.assertIn('self.extract_button.setObjectName("primary")', self.source)
        self.assertNotIn('self.link_button.setObjectName("primary")', self.source)
        self.assertLess(
            self.source.index("actions.addWidget(self.extract_card"),
            self.source.index("actions.addWidget(self.link_card"),
        )
        self.assertIn('t("Extraire ma collection")', self.source)
        self.assertIn('t("Relier un export existant")', self.source)

    def test_maintenance_actions_are_separated_and_explained(self) -> None:
        self.assertIn("maintenance_actions.addWidget(self.catalog_button)", self.source)
        self.assertIn("maintenance_actions.addWidget(self.force_link_button)", self.source)
        self.assertIn("maintenance_actions.addWidget(self.open_button)", self.source)
        self.assertGreaterEqual(self.source.count(".setToolTip("), 9)


class TransferGuidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (PROJECT_DIR / "ui_qt" / "pages_transfer.py").read_text(
            encoding="utf-8"
        )

    def test_transfer_controls_and_verdicts_have_contextual_help(self) -> None:
        targets = ("run_button", "menu_button", "search", "table")
        for target in targets:
            with self.subTest(target=target):
                self.assertIn(f"self.{target}.setToolTip(", self.source)

    def test_new_guidance_is_translated(self) -> None:
        strings = (
            "Extraire ma collection",
            "Relier un export existant",
            "Maintenance et fichiers",
            "Historique, portée de l’analyse et dossier de sortie.",
            "Rechercher par nom ou score…",
            "Remplacée par {score}",
            "Couverte par {first} + {second}",
            "Jamais dans le top",
            "À vérifier — couverture insuffisante",
        )
        for source in strings:
            with self.subTest(source=source):
                self.assertNotEqual(translate_text(source, "en"), source)

    def test_transfer_has_no_decision_panel_or_costume_filter(self) -> None:
        self.assertNotIn("TransferDecisionPanel", self.source)
        self.assertNotIn("family_combo", self.source)
        self.assertIn("def _reason_tooltip", self.source)
        self.assertIn("def open_audit", self.source)

    def test_transfer_report_freshness_is_explicit(self) -> None:
        for state in (
            "STATE_EMPTY",
            "STATE_RUNNING",
            "STATE_READY",
            "STATE_STALE",
            "STATE_LOADED",
            "STATE_REANALYZE",
        ):
            self.assertIn(state, self.source)
        self.assertIn("transfer_fingerprint", self.source)
        self.assertIn("generated_at_utc", self.source)
        self.assertIn("calendar_valid_until", self.source)


class FinalPolishSourceTests(unittest.TestCase):
    def test_main_window_constructs_pages_lazily_and_owns_shortcuts(self) -> None:
        source = (PROJECT_DIR / "ui_qt" / "main_window.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('self._ensure_page("home")', source)
        self.assertIn("def _ensure_page", source)
        self.assertIn('QKeySequence(f"Ctrl+{index}")', source)
        self.assertIn('("Ctrl+Return", "Ctrl+Enter")', source)
        self.assertIn("setAccessibleName", source)

    def test_weights_page_has_one_save_model(self) -> None:
        source = (PROJECT_DIR / "ui_qt" / "pages_weights.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("self.apply_button", source)
        self.assertIn("def _commit_pending_editor", source)
        self.assertIn('t("Enregistrer le profil")', source)
        self.assertIn("Modifications non enregistrées", source)

    def test_online_launch_only_snapshots_widgets_on_the_gui_thread(self) -> None:
        source = (PROJECT_DIR / "ui_qt" / "pages_search.py").read_text(
            encoding="utf-8"
        )
        start_online = source[source.index("    def start_online(") :]
        self.assertIn("self._online_options_snapshot(mode)", start_online)
        self.assertNotIn("self._online_options_values(mode)", start_online)


class OnlineOptionMaterializationTests(unittest.TestCase):
    def test_worker_normalizes_and_detaches_the_widget_snapshot(self) -> None:
        payload = {"lineage": [{"card_id": 1001}]}
        request = OnlineSearchRequest(
            search_mode="grandparent",
            master_path=Path("master.mdb"),
            veterans_json_path=Path("veterans.json"),
            output_dir=Path("output"),
            ace_card_id=1,
            target_parent_card_id=2,
            fixed_local_id=None,
            automatic_pairs=True,
            local_pool_size=10,
            remote_pool_size=20,
            surface="turf",
            distance="mile",
            style="pace",
            deferred_options={
                "uql_options": {"pink_min_stars": 2},
                "fixed_local_id": 42,
                "automatic_pairs": False,
                "local_pool_size": 30,
                "remote_pool_size": 50,
                "limit": 1200,
                "planned_g1_budget": 18,
                "g1_win_probability_cutoff": 0.75,
                "required_parent_card_id": 7,
                "allowed_parent_card_ids": (9, 3, 9),
                "excluded_parent_card_ids": (8, 4),
                "opposing_parent_trained_id": 81,
                "opposing_parent_payload": payload,
                "response_path": "~/uma-response.json",
                "lineage_blue_filter": ("Speed", 2),
                "lineage_pink_filter": ("Mile", 3),
            },
        )

        materialized = materialize_online_search_options(request)

        self.assertEqual(materialized.allowed_parent_card_ids, (3, 9))
        self.assertEqual(materialized.excluded_parent_card_ids, (4, 8))
        self.assertEqual(materialized.fixed_local_id, 42)
        self.assertFalse(materialized.automatic_pairs)
        self.assertEqual(materialized.local_pool_size, 30)
        self.assertEqual(materialized.remote_pool_size, 50)
        self.assertEqual(materialized.limit, 1200)
        self.assertEqual(materialized.planned_g1_budget, 18)
        self.assertEqual(materialized.g1_win_probability_cutoff, 0.75)
        self.assertEqual(materialized.required_parent_card_id, 7)
        self.assertEqual(materialized.opposing_parent_trained_id, 81)
        self.assertEqual(materialized.opposing_parent_payload, payload)
        self.assertIsNot(materialized.opposing_parent_payload, payload)
        self.assertEqual(materialized.lineage_blue_filter, ("Speed", 2))
        self.assertEqual(materialized.lineage_pink_filter, ("Mile", 3))
        self.assertEqual(
            materialized.response_path, Path("~/uma-response.json").expanduser()
        )
        self.assertIsNone(materialized.deferred_options)


if __name__ == "__main__":
    unittest.main()

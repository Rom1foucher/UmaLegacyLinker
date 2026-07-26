from __future__ import annotations

import json
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_i18n import FRENCH_MARKERS
from i18n import scoring_label, translate_text
from parent_optimizer import OptimizerError
from scoring_config import iter_leaf_paths, read_json_object
from ui_qt.core import (
    OnlineSearchRequest,
    OptimizationRequest,
    SettingsStore,
    TransferRequest,
    VeteranOption,
    collection_size,
    load_rankings_payload,
    run_online_search,
    run_optimization,
    run_transfer_analysis,
)
from ui_qt.lineage_nodes import build_pair_lineage_nodes
from ui_qt.presentation import (
    online_detail_html,
    result_detail_html,
    transfer_detail_html,
)
from ui_qt.theme import (
    APTITUDE_COLORS,
    COLORS,
    RANK_BADGE_COLORS,
    SPARK_COLORS,
)
from ui_qt.weight_controls import (
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
from ui_qt.weight_help import describe_weight
from uma_moe import UmaMoeError


class QtUiCoreTests(unittest.TestCase):
    def test_weight_editor_groups_settings_by_user_facing_role(self) -> None:
        cases = {
            ("mode_weights", "parent_pair", "blue"): "global",
            ("aptitude_inheritance", "pink_base_proc_rates", "3"): "aptitudes",
            ("blue_stat_weights_by_distance", "long", "Stamina"): "blue",
            ("white_inheritance", "base_proc_rates", "2"): "white",
            ("star_quality", "3"): "affinity",
            ("affinity", "g1_common_bonus"): "affinity",
            ("course_conditions", "floors", "weather"): "course",
            ("future_grandparent_heuristics", "pink_star_quality", "3"): "future_gp",
            ("unique_star_quality", "3"): "unique",
            ("uma_moe_pair", "final_branch_thresholds"): "online",
            ("transfer_helper", "competitive_utility_floor"): "transfer",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(weight_category(path), expected)

    def test_weight_editor_distinguishes_probabilities_and_relative_weights(self) -> None:
        probability = ("white_inheritance", "base_proc_rates", "3")
        relative = ("mode_weights", "parent_pair", "blue")
        integer_points = (
            "aptitude_inheritance",
            "distance",
            "start_a_s_probability_weight",
        )
        self.assertTrue(is_percentage_setting(probability, 0.09))
        self.assertTrue(is_probability_setting(probability))
        self.assertEqual(percentage_limit(probability, 0.09), 100.0)
        self.assertTrue(is_percentage_setting(relative, 0.2))
        self.assertFalse(is_probability_setting(relative))
        self.assertEqual(percentage_limit(relative, 0.2), 100.0)
        self.assertEqual(percentage_limit(relative, 1.8), 200.0)
        self.assertFalse(is_percentage_setting(integer_points, 30))
        self.assertEqual(percentage_display(0.3333333333), "33.33 %")
        self.assertTrue(
            is_threshold_percentage(
                ("transfer_helper", "competitive_utility_floor")
            )
        )
        self.assertFalse(is_threshold_percentage(probability))

    def test_spark_highlights_distinguish_major_useful_and_scenario(self) -> None:
        names = ["Priority One", "Priority Two", "Priority Three", "Useful Four"]
        nodes = build_pair_lineage_nodes(
            {"card_name": "Ace"},
            {
                "parent_1": {"card_name": "Parent"},
                "parent_2": {"card_name": "Other"},
                "lineage_preview": {
                    "p1": {
                        "card_name": "Parent",
                        "sparks": [
                            {"name": name, "stars": 2, "type": "white_skill"}
                            for name in reversed(names)
                        ]
                        + [{"name": "Grand Concert", "stars": 2, "type": "scenario"}],
                    }
                },
                "component_details": {
                    "white_skill": {
                        "top_skills": [
                            {
                                "name": name,
                                "catalog_key": name.lower().replace(" ", "_"),
                                "profile_weight": 0.5,
                                "contribution": 1.0 / rank,
                            }
                            for rank, name in enumerate(names, 1)
                        ],
                        "factors": [
                            {
                                "role": "parent_1",
                                "source_type": "white_skill",
                                "source_factor_name": name,
                                "catalog_key": name.lower().replace(" ", "_"),
                                "stars": 2,
                                "profile_weight": 0.5,
                                "contribution": 1.0 / rank,
                                "proc_probability_over_run": 0.12,
                            }
                            for rank, name in enumerate(names, 1)
                        ],
                    }
                },
            },
        )
        whites = [
            factor for factor in nodes["p1"]["sparks"] if factor["type"] == "white_skill"
        ]
        self.assertEqual([factor["name"] for factor in whites], names)
        self.assertEqual(
            [bool(factor.get("is_score_priority")) for factor in whites],
            [True, True, True, False],
        )
        self.assertTrue(whites[3]["is_score_useful"])
        self.assertNotEqual(SPARK_COLORS["scenario"], SPARK_COLORS["white_priority"])
        self.assertNotEqual(SPARK_COLORS["white_useful"], SPARK_COLORS["white_priority"])

    def test_weight_groups_preview_normalised_shares_without_mutation(self) -> None:
        config = read_json_object(Path(__file__).parent / "default_parent_scoring.json")
        path = ("mode_weights", "parent_pair", "distance_s")
        paths = relative_group_paths(config, path)
        shares = relative_group_shares(config, path)
        self.assertEqual(len(paths), 7)
        self.assertAlmostEqual(sum(share for _path, share in shares), 1.0)
        self.assertAlmostEqual(dict(shares)[path], 0.29)

        original_values = {item: config[item[0]][item[1]][item[2]] for item in paths}
        preview = relative_group_shares_with_value(config, path, 0.40)
        self.assertAlmostEqual(sum(share for _path, share in preview), 1.0)
        expected_total = sum(original_values.values()) - original_values[path] + 0.40
        self.assertAlmostEqual(dict(preview)[path], 0.40 / expected_total)
        self.assertEqual(
            {item: config[item[0]][item[1]][item[2]] for item in paths},
            original_values,
        )
        self.assertEqual(
            relative_group_paths(
                config, ("blue_stat_weights_by_distance", "long", "Stamina")
            ),
            (),
        )
        hidden = {"schema_version", "description", "formula_notes", "notes", "weight_source"}
        groups = {
            relative_group_paths(config, item)
            for item, _value in iter_leaf_paths(config)
            if not any(key in hidden or key.endswith("description") for key in item)
            and relative_group_paths(config, item)
        }
        self.assertEqual(len(groups), 7)
        self.assertEqual(sum(len(group) for group in groups), 32)

    def test_subcategories_cover_every_weight_in_curated_order(self) -> None:
        config = read_json_object(Path(__file__).parent / "default_parent_scoring.json")
        hidden = {"schema_version", "description", "formula_notes", "notes", "weight_source"}
        paths = [
            path
            for path, _value in iter_leaf_paths(config)
            if not any(key in hidden or key.endswith("description") for key in path)
        ]
        sources = {weight_subcategory(path)[1] for path in paths}
        self.assertEqual(len(sources), 51)
        self.assertNotIn("Autres réglages", sources)
        for source in sources:
            with self.subTest(source=source):
                self.assertNotEqual(translate_text(source, "en"), source)
        ordered = sorted(paths, key=weight_sort_key)
        self.assertEqual(ordered[0][:2], ("mode_weights", "parent_branch"))
        self.assertEqual(ordered[-1][0], "transfer_helper")

    def test_visible_weight_names_never_fall_back_to_json_keys(self) -> None:
        config = read_json_object(Path(__file__).parent / "default_parent_scoring.json")
        hidden = {"schema_version", "description", "formula_notes", "notes", "weight_source"}
        missing: list[str] = []
        for path, _value in iter_leaf_paths(config):
            if any(key in hidden or key.endswith("description") for key in path):
                continue
            for language in ("fr", "en"):
                for key in path:
                    if "_" in key and scoring_label(key, language) == key:
                        missing.append(f"{language}: {key}")
        self.assertEqual(missing, [])

    def test_every_visible_weight_has_bilingual_contextual_help(self) -> None:
        config = read_json_object(Path(__file__).parent / "default_parent_scoring.json")
        hidden = {"schema_version", "description", "formula_notes", "notes", "weight_source"}
        checked = 0
        for path, value in iter_leaf_paths(config):
            if any(key in hidden or key.endswith("description") for key in path):
                continue
            french = describe_weight(path, value, "fr")
            english = describe_weight(path, value, "en")
            with self.subTest(path=path):
                self.assertTrue(french.summary)
                self.assertTrue(french.impact)
                self.assertTrue(french.scope)
                self.assertTrue(french.low_label)
                self.assertTrue(french.high_label)
                self.assertTrue(english.summary)
                self.assertTrue(english.impact)
                self.assertTrue(english.scope)
                self.assertTrue(english.low_label)
                self.assertTrue(english.high_label)
                self.assertNotEqual(french.summary, english.summary)
                self.assertFalse(french.summary.startswith("Règle «"))
            checked += 1
        self.assertEqual(checked, 216)

    def test_settings_updates_preserve_legacy_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"uma_moe_query": "distance = 3", "ui_language": "fr"}),
                encoding="utf-8",
            )
            store = SettingsStore(path)
            store.update({"master_path": "C:/game/master.mdb"})
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["uma_moe_query"], "distance = 3")
            self.assertEqual(saved["master_path"], "C:/game/master.mdb")

    def test_collection_size_supports_export_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.json"
            path.write_text(
                json.dumps({"trained_chara_array": [{"id": 1}, {"id": 2}]}),
                encoding="utf-8",
            )
            self.assertEqual(collection_size(path), 2)

    def test_latest_result_payload_must_be_an_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ranking.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(OptimizerError, "objet JSON"):
                load_rankings_payload(path)

    def test_result_diagnostic_escapes_names_and_keeps_score(self) -> None:
        row = {
            "score": 82.25,
            "parent_1": {"card_name": "A < B"},
            "parent_2": {"card_name": "C & D"},
            "affinity": {"total": 151, "base": 142, "g1_bonus": 9},
            "components": {"blue": 75},
            "distance_viability": {"key": "ready_for_s", "tier": 4},
            "distance_s_summary": {"probability_reach_s": 0.52},
        }
        rendered = result_detail_html(row, "pair", "en", {"distance": "medium"})
        self.assertIn("82.25", rendered)
        self.assertIn("A &lt; B", rendered)
        self.assertNotIn("A < B", rendered)
        self.assertIn("Ready for S", rendered)

    def test_result_summary_uses_game_style_aptitudes_and_aggregates_parent_branches(self) -> None:
        row = {
            "score": 66.37,
            "parent_1": {"card_name": "Parent One"},
            "parent_2": {"card_name": "Parent Two"},
            "affinity": {"total": 215},
            "distance_viability": {"key": "ready_for_s", "tier": 4},
            "distance_s_summary": {
                "base_rank_label": "A",
                "initial_rank_label": "A",
                "probability_reach_a": 1.0,
                "probability_reach_s": 0.44,
            },
            "aptitude_summaries": {
                "surface": {
                    "base_rank_label": "B",
                    "initial_rank_label": "A",
                    "probability_reach_s": 0.13,
                },
                "style": {
                    "base_rank_label": "A",
                    "initial_rank_label": "A",
                    "probability_reach_s": 0.0,
                },
            },
            "lineage_preview": {
                "p1": {
                    "card_name": "Parent One",
                    "sparks": [
                        {"name": "Speed", "stars": 3, "type": "blue_stat"},
                        {"name": "Medium", "stars": 2, "type": "red_aptitude"},
                        {"name": "Unique One", "stars": 1, "type": "unique"},
                        {
                            "name": "Corner Adept",
                            "stars": 2,
                            "type": "white_skill",
                            "proc_probability_over_run": 0.2298,
                        },
                    ],
                },
                "p2": {
                    "card_name": "Parent Two",
                    "sparks": [
                        {"name": "Stamina", "stars": 3, "type": "blue_stat"},
                    ],
                },
                "p1-1": {
                    "card_name": "Grandparent One A",
                    "sparks": [
                        {"name": "Speed", "stars": 3, "type": "blue_stat"},
                        {"name": "Turf", "stars": 1, "type": "red_aptitude"},
                        {
                            "name": "Corner Adept",
                            "stars": 2,
                            "type": "white_skill",
                            "proc_probability_over_run": 0.1565,
                        },
                        {"name": "Tail Held High", "stars": 2, "type": "white_skill"},
                    ],
                },
                "p1-2": {
                    "card_name": "Grandparent One B",
                    "sparks": [
                        {"name": "Speed", "stars": 3, "type": "blue_stat"},
                        {"name": "Medium", "stars": 1, "type": "red_aptitude"},
                    ],
                },
            },
            "component_details": {
                "white_skill": {
                    "inspiration_event_count": 2,
                    "factors": [
                        {
                            "role": "parent_1",
                            "source_type": "white_skill",
                            "source_factor_name": "Corner Adept",
                            "stars": 2,
                            "proc_probability_over_run": 0.2298,
                        },
                        {
                            "role": "parent_1_grandparent_1",
                            "source_type": "white_skill",
                            "source_factor_name": "Corner Adept",
                            "stars": 2,
                            "proc_probability_over_run": 0.1565,
                        },
                    ],
                }
            },
            "components": {"blue": 53.21},
        }
        rendered = result_detail_html(
            row,
            "pair",
            "en",
            {"surface": "dirt", "distance": "medium", "style": "pace_chaser"},
        )
        self.assertIn("rank-S", rendered)
        self.assertIn("Spark summary by parent", rendered)
        self.assertIn("Dirt", rendered)
        self.assertIn("Medium", rendered)
        self.assertIn("Pace Chaser", rendered)
        self.assertIn("<b>9★</b>", rendered)
        self.assertIn(">Speed</td>", rendered)
        self.assertIn(">×3</td>", rendered)
        self.assertIn("Corner Adept", rendered)
        self.assertEqual(rendered.count(">Corner Adept</td>"), 1)
        self.assertIn("<b>4★</b>", rendered)
        # 1 - (1 - 0.2298) × (1 - 0.1565) = 0.3503 : probabilité qu'au moins un
        # des deux porteurs de la branche fasse procer la skill sur la run.
        self.assertIn("×2 · 35.03%", rendered)
        self.assertIn("Tail Held High", rendered)
        self.assertIn("Unique One", rendered)
        self.assertIn("parent-marker", rendered)
        self.assertIn("class='spark-grid' width='100%'", rendered)
        self.assertIn("class='spark-owner' width='100%'", rendered)
        self.assertIn("class='spark-families' width='100%'", rendered)
        self.assertIn("class='spark-card' width='100%'", rendered)
        self.assertNotIn("class='spark-chip'", rendered)
        self.assertIn("class='aptitude-table' width='100%'", rendered)
        self.assertIn("class='aptitude-heading'", rendered)
        self.assertIn("class='rank-badge-table'", rendered)
        self.assertLess(rendered.index("Blue Sparks"), rendered.index("Pink Sparks"))
        self.assertLess(rendered.index("Pink Sparks"), rendered.index("Green Sparks"))
        self.assertLess(rendered.index("Green Sparks"), rendered.index("Other Sparks"))

    def test_detail_stylesheets_avoid_selectors_qt_silently_rejects(self) -> None:
        # Qt abandonne le reste d'une feuille de style dès qu'il rencontre un
        # sélecteur qu'il ne sait pas lire : une seule règle « td:nth-child »
        # suffisait à rendre muettes toutes les règles déclarées après elle.
        unsupported = ("nth-child", "nth-of-type", ":hover", "::", "~=", " > ", " + ")
        panels = [
            result_detail_html(
                {"score": 1.0, "parent_1": {"card_name": "A"}, "parent_2": {"card_name": "B"}},
                "pair",
                "fr",
            ),
            online_detail_html(
                {
                    "score": 1.0,
                    "fixed_parent": {"card_name": "A"},
                    "candidate": {"card_name": "B", "online": {"friend_code": "1"}},
                },
                "parent",
                "fr",
            ),
            transfer_detail_html({"card_name": "A", "status": "keep"}, "fr"),
        ]
        for panel in panels:
            for block in panel.split("<style>")[1:]:
                stylesheet = block.split("</style>")[0]
                for selector in unsupported:
                    with self.subTest(selector=selector):
                        self.assertNotIn(selector, stylesheet)

    def test_transfer_detail_explains_spark_protection_deficits(self) -> None:
        row = {
            "card_name": "Candidate",
            "status": "likely_keep",
            "reason_code": "protected_direct_future_gp_spark",
            "dominated_by": {
                "card_name": "Replacement",
                "mean_score_lead": 2.5,
                "worst_context_delta": 0.5,
            },
            "spark_protection": {
                "applied": True,
                "verdict_floor": "likely_keep",
                "reason_codes": [
                    "protected_direct_future_gp_spark",
                    "protected_important_skill_set",
                ],
                "deficits": [
                    {
                        "kind": "skill",
                        "name": "Nimble Navigator",
                        "candidate": {
                            "present": True,
                            "carrier_count": 2,
                            "total_stars": 5,
                            "neutral_probability": 0.267,
                            "direct": True,
                            "direct_total_stars": 3,
                            "white_generation_carrier_count": 2,
                            "direct_support_hint_card_count": 0,
                        },
                        "replacement": {
                            "present": True,
                            "carrier_count": 1,
                            "total_stars": 2,
                            "neutral_probability": 0.116,
                            "direct": False,
                        },
                    },
                    {
                        "kind": "package",
                        "label": "General backliner core",
                        "candidate_distinct_count": 3,
                        "replacement_distinct_count": 3,
                        "candidate_total_stars": 8,
                        "replacement_total_stars": 6,
                        "missing_skills": [],
                        "degraded_skills": ["ramp_up", "uma_stan"],
                    },
                ],
            },
        }

        rendered = transfer_detail_html(row, "en")

        self.assertIn("Spark heritage protection", rendered)
        self.assertIn("Nimble Navigator", rendered)
        self.assertIn("2 carrier(s)", rendered)
        self.assertIn("direct 3★", rendered)
        self.assertIn("generation ×2", rendered)
        self.assertIn("0 support card(s) with a direct hint", rendered)
        self.assertIn("General backliner core", rendered)
        self.assertIn("Reduced coverage: Ramp Up, Uma Stan", rendered)

    def test_detail_html_uses_qt_compatible_tables_for_spacing(self) -> None:
        row = {
            "score": 72.08,
            "parent_1": {"card_name": "Parent One"},
            "parent_2": {"card_name": "Parent Two"},
            "affinity": {"total": 293},
            "distance_viability": {"key": "ready_for_s", "tier": 4},
            "distance_s_summary": {
                "base_rank_label": "A",
                "initial_rank_label": "A",
                "probability_reach_s": 0.404,
            },
            "aptitude_summaries": {
                "surface": {
                    "base_rank_label": "B",
                    "initial_rank_label": "A",
                    "probability_reach_s": 0.35,
                },
            },
        }
        rendered = result_detail_html(row, "pair", "en", {"surface": "dirt"})
        self.assertIn("class='metric-card'", rendered)
        self.assertIn("class='facts-table'", rendered)
        self.assertIn("class='aptitude-name'", rendered)
        self.assertIn("class='metric-row' width='100%'", rendered)
        self.assertIn("class='facts-table' width='100%'", rendered)
        self.assertIn("class='component-table' width='100%'", rendered)
        self.assertNotIn("display:flex", rendered)
        self.assertNotIn("display:grid", rendered)

    def test_optimizer_detail_browser_exists_before_sorting_can_emit_layout_changed(self) -> None:
        source = (
            Path(__file__).parent / "ui_qt" / "pages_optimizer.py"
        ).read_text(encoding="utf-8")
        result_pane = source[source.index("class ResultPane"):source.index("class OptimizerPage")]
        self.assertLess(
            result_pane.index("self.detail = QTextBrowser()"),
            result_pane.index("self.model.layoutChanged.connect"),
        )
        self.assertLess(
            result_pane.index("self.detail = QTextBrowser()"),
            result_pane.index("self.table.sortByColumn"),
        )

    def test_online_parent_summary_uses_the_same_three_member_branch_totals(self) -> None:
        row = {
            "score": 81.0,
            "fixed_parent": {
                "card_name": "Local Parent",
                "sparks": [{"name": "Stamina", "stars": 3, "type": "blue_stat"}],
            },
            "candidate": {
                "card_name": "Remote Parent",
                "sparks": [{"name": "Power", "stars": 3, "type": "blue_stat"}],
                "online": {"friend_code": "123", "trainer_name": "Trainer"},
            },
            "lineage_preview": {
                "p1": {
                    "card_name": "Local Parent",
                    "sparks": [{"name": "Stamina", "stars": 3, "type": "blue_stat"}],
                },
                "p1-1": {
                    "card_name": "Local GP A",
                    "sparks": [{"name": "Stamina", "stars": 3, "type": "blue_stat"}],
                },
                "p1-2": {
                    "card_name": "Local GP B",
                    "sparks": [{"name": "Stamina", "stars": 3, "type": "blue_stat"}],
                },
                "p2": {
                    "card_name": "Remote Parent",
                    "sparks": [{"name": "Power", "stars": 3, "type": "blue_stat"}],
                },
            },
        }
        rendered = online_detail_html(row, "parent", "en")
        self.assertIn("Spark summary by parent", rendered)
        self.assertIn("<b>9★</b>", rendered)
        self.assertIn(">Stamina</td>", rendered)
        self.assertIn(">×3</td>", rendered)
        self.assertIn("present on the direct parent", rendered)

    def test_qt_navigation_and_diagnostics_are_translated(self) -> None:
        sources = (
            "Vue d’ensemble",
            "Données locales",
            "Résultats intégrés",
            "Calcul du score global",
            "Sélectionne une ligne pour afficher le diagnostic.",
            "Interface Qt complète",
        )
        for source in sources:
            with self.subTest(source=source):
                self.assertNotEqual(translate_text(source, "en"), source)

    def test_optimizer_ui_uses_the_existing_backend_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.mdb"
            veterans = root / "data.json"
            master.touch()
            veterans.write_text("[]", encoding="utf-8")
            linked = SimpleNamespace(
                json_path=root / "veterans_legacy_linked.json",
                skills_catalog_path=root / "skills.json",
                race_factor_skills_path=root / "race_skills.json",
            )
            manual = SimpleNamespace(
                weights_path=root / "manual_skill_weights.json",
                course_weights_path=root / "course_skill_weights.json",
            )
            expected = object()
            request = OptimizationRequest(
                master_path=master,
                veterans_json_path=veterans,
                output_dir=root,
                ace_card_id=1001,
                future_parent_card_id=1002,
                surface="turf",
                distance="medium",
                style="pace_chaser",
                course_key="test_course",
                course_conditions={"weather": 1},
            )
            with (
                patch("ui_qt.core.link_veterans", return_value=linked) as link,
                patch("ui_qt.core.generate_manual_skill_weights", return_value=manual) as weights,
                patch("ui_qt.core.optimize_parents", return_value=expected) as optimise,
            ):
                result = run_optimization(
                    request,
                    logger=lambda _message: None,
                    progress=lambda _value, _message: None,
                )
            self.assertIs(result, expected)
            link.assert_called_once()
            weights.assert_called_once()
            self.assertEqual(optimise.call_args.kwargs["ace_card_id"], 1001)
            self.assertEqual(optimise.call_args.kwargs["course_key"], "test_course")
            self.assertEqual(
                optimise.call_args.kwargs["course_conditions"], {"weather": 1}
            )

    def test_transfer_page_uses_existing_analysis_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.mdb"
            veterans = root / "data.json"
            master.touch()
            veterans.write_text("[]", encoding="utf-8")
            linked = SimpleNamespace(
                json_path=root / "linked.json",
                skills_catalog_path=root / "skills.json",
                race_factor_skills_path=root / "race.json",
            )
            manual = SimpleNamespace(
                weights_path=root / "weights.json",
                course_weights_path=root / "courses.json",
            )
            expected = object()
            request = TransferRequest(master, veterans, root)
            with (
                patch("ui_qt.core.link_veterans", return_value=linked),
                patch("ui_qt.core.generate_manual_skill_weights", return_value=manual),
                patch("ui_qt.core.analyze_transfer_candidates", return_value=expected) as analyse,
            ):
                result = run_transfer_analysis(
                    request,
                    logger=lambda _message: None,
                    progress=lambda _value, _message: None,
                )
            self.assertIs(result, expected)
            self.assertEqual(analyse.call_args.args[1], linked.json_path)
            self.assertEqual(
                analyse.call_args.kwargs["course_weights_path"], manual.course_weights_path
            )

    def test_online_parent_mode_reuses_exact_pair_ranker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.mdb"
            veterans = root / "data.json"
            response = root / "response.json"
            master.touch()
            veterans.write_text("[]", encoding="utf-8")
            response.write_text('{"records": []}', encoding="utf-8")
            linked = SimpleNamespace(
                json_path=root / "linked.json",
                skills_catalog_path=root / "skills.json",
                race_factor_skills_path=root / "race.json",
            )
            manual = SimpleNamespace(
                weights_path=root / "weights.json",
                course_weights_path=root / "courses.json",
            )
            expected = object()
            request = OnlineSearchRequest(
                search_mode="parent",
                master_path=master,
                veterans_json_path=veterans,
                output_dir=root,
                ace_card_id=1001,
                target_parent_card_id=None,
                fixed_local_id=None,
                automatic_pairs=True,
                local_pool_size=50,
                remote_pool_size=60,
                surface="turf",
                distance="medium",
                style="pace_chaser",
                use_import=True,
                response_path=response,
            )
            with (
                patch("ui_qt.core.link_veterans", return_value=linked),
                patch("ui_qt.core.generate_manual_skill_weights", return_value=manual),
                patch("ui_qt.core.generate_auto_uql", return_value=("", {"search_filters": {}})),
                patch("ui_qt.core.rank_online_parent_pairs", return_value=expected) as ranker,
            ):
                result = run_online_search(
                    request,
                    logger=lambda _message: None,
                    progress=lambda _value, _message: None,
                )
            self.assertIs(result, expected)
            self.assertEqual(ranker.call_args.kwargs["ace_card_id"], 1001)
            self.assertEqual(ranker.call_args.kwargs["local_pool_size"], 50)
            self.assertEqual(ranker.call_args.kwargs["remote_pool_size"], 60)

    def test_fixed_gp_cannot_match_target_parent_character(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            master = root / "master.mdb"
            veterans = root / "data.json"
            response = root / "response.json"
            master.touch()
            veterans.write_text("[]", encoding="utf-8")
            response.write_text("{}", encoding="utf-8")
            request = OnlineSearchRequest(
                search_mode="grandparent",
                master_path=master,
                veterans_json_path=veterans,
                output_dir=root,
                ace_card_id=1001,
                target_parent_card_id=2002,
                fixed_local_id=77,
                automatic_pairs=False,
                local_pool_size=10,
                remote_pool_size=10,
                surface="turf",
                distance="medium",
                style="pace_chaser",
                use_import=True,
                response_path=response,
            )
            ace_options = [
                SimpleNamespace(card_id=1001, chara_id=1),
                SimpleNamespace(card_id=2002, chara_id=2),
            ]
            local = VeteranOption(77, 2999, 2, "Target", "Alt costume", 9000)
            with (
                patch("ui_qt.core.load_ace_options", return_value=ace_options),
                patch("ui_qt.core.load_local_veteran_options", return_value=[local]),
            ):
                with self.assertRaisesRegex(UmaMoeError, "même Uma"):
                    run_online_search(
                        request,
                        logger=lambda _message: None,
                        progress=lambda _value, _message: None,
                    )

    def test_semantic_theme_colours_have_readable_contrast(self) -> None:
        def channel(value: int) -> float:
            normalized = value / 255.0
            return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4

        def luminance(colour: str) -> float:
            red, green, blue = (int(colour[index:index + 2], 16) for index in (1, 3, 5))
            return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

        def contrast(first: str, second: str) -> float:
            high, low = sorted((luminance(first), luminance(second)), reverse=True)
            return (high + 0.05) / (low + 0.05)

        for foreground in ("text", "muted", "accent", "blue", "warning", "danger"):
            with self.subTest(foreground=foreground):
                self.assertGreaterEqual(
                    contrast(COLORS[foreground], COLORS["background"]), 4.5
                )
        for foreground, background in (
            ("text", "surface"),
            ("muted", "surface"),
            ("accent", "accent_dark"),
        ):
            self.assertGreaterEqual(
                contrast(COLORS[foreground], COLORS[background]), 4.5
            )
        self.assertGreaterEqual(contrast("#07120f", COLORS["accent"]), 4.5)
        for spark_type, (background, _border, foreground) in SPARK_COLORS.items():
            with self.subTest(spark_type=spark_type):
                self.assertGreaterEqual(contrast(foreground, background), 4.5)
        for rank, (background, _border, foreground) in RANK_BADGE_COLORS.items():
            with self.subTest(rank=rank):
                self.assertGreaterEqual(contrast(foreground, background), 4.5)
        self.assertGreaterEqual(contrast("#171104", "#f3c85b"), 4.5)
        for foreground in ("cell_foreground", "name", "S", "A", "B", "C", "D", "other"):
            with self.subTest(aptitude=foreground):
                self.assertGreaterEqual(
                    contrast(
                        APTITUDE_COLORS[foreground],
                        APTITUDE_COLORS["cell_background"],
                    ),
                    4.3,
                )
        self.assertGreaterEqual(
            contrast(
                APTITUDE_COLORS["header_foreground"],
                APTITUDE_COLORS["header_background"],
            ),
            4.5,
        )
        for foreground, background in (
            ("#dce9f8", COLORS["surface"]),
            ("#b7c6d9", "#1a2738"),
            ("#8de8ca", "#173b36"),
            ("#f7d487", "#3b301b"),
            (COLORS["blue"], "#112331"),
        ):
            self.assertGreaterEqual(contrast(foreground, background), 4.5)

    def test_visible_qt_copy_has_an_english_translation(self) -> None:
        neutral = {
            "Transfer Helper", "Score", "Trainer", "Surface", "Distance", "Distance S",
            "Whites", "ID", "Copies", "Minimum pink", "Parent", "Parent 1", "Parent 2", "Local",
            "G1", "Points", "Aptitude", "Sparks", "Export", "Verdict", "base",
            "Support",
            "Fichier introuvable", "Profil par défaut actif", "Profil personnalisé actif",
        }
        missing: list[str] = []
        for path in (Path(__file__).parent / "ui_qt").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                source = node.args[0]
                if not isinstance(source, ast.Constant) or not isinstance(source.value, str):
                    continue
                is_translation = (
                    isinstance(node.func, ast.Name) and node.func.id in {"t", "_t"}
                ) or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "t"
                )
                if not is_translation or source.value in neutral:
                    continue
                if any(character.isalpha() for character in source.value):
                    english = translate_text(source.value, "en")
                    if english == source.value:
                        missing.append(f"{path.name}:{node.lineno}: {source.value}")
                    elif FRENCH_MARKERS.search(english):
                        # Partial fragment substitution: the exact key never
                        # matched (a straight/typographic apostrophe mismatch
                        # is the usual cause) and the copy stays French.
                        missing.append(
                            f"{path.name}:{node.lineno}: still French after "
                            f"translation: {english[:80]}"
                        )
        self.assertEqual(missing, [], "Missing Qt translations:\n" + "\n".join(missing))


if __name__ == "__main__":
    unittest.main()

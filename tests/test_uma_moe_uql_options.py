from __future__ import annotations

import json
import io
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from uma_moe import (
    UmaMoeError,
    UmaMoeApiClient,
    build_lineage_factor_api_filters,
    generate_auto_uql,
)


class UmaMoeUqlOptionTests(unittest.TestCase):
    def _generate(self, options: dict[str, object]) -> tuple[str, dict[str, object]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            weights = root / "weights.json"
            catalog = root / "catalog.json"
            weights.write_text(json.dumps({"skills": {}}), encoding="utf-8")
            catalog.write_text(json.dumps({"skills": []}), encoding="utf-8")
            return generate_auto_uql(
                weights,
                catalog,
                surface="dirt",
                distance="mile",
                style="pace_chaser",
                options=options,
            )

    def test_target_surface_replaces_the_obsolete_dirt_toggle(self) -> None:
        uql, metadata = self._generate(
            {
                "require_main_surface": True,
                "pink_min_stars": 2,
            }
        )

        self.assertIn("Main Dirt >= 2", uql)
        self.assertEqual(
            metadata["hard_filters"],
            [
                {
                    "slot": "main",
                    "factor": "Dirt",
                    "minimum_stars": 2,
                    "uql": "Main Dirt >= 2",
                }
            ],
        )

    def test_search_uses_explicit_quality_sort_and_allows_override(self) -> None:
        payload = {
            "items": [
                {"inheritance": {"inheritance_id": 1, "factor_ids": [101]}}
            ]
        }
        client = UmaMoeApiClient("https://example.invalid/api")
        with patch.object(client, "_request_json", return_value=payload) as request:
            client.search()
        query = request.call_args.kwargs["query"]
        self.assertEqual(query["sort_by"], "white_count")
        self.assertEqual(query["sort_order"], "desc")

        with patch.object(client, "_request_json", return_value=payload) as request:
            client.search(filters={"sort_by": "affinity_score", "sort_order": "asc"})
        query = request.call_args.kwargs["query"]
        self.assertEqual(query["sort_by"], "affinity_score")
        self.assertEqual(query["sort_order"], "asc")

    def test_search_distinguishes_empty_and_malformed_responses(self) -> None:
        client = UmaMoeApiClient("https://example.invalid/api")
        with patch.object(
            client,
            "_request_json",
            return_value={"items": [], "total": "0"},
        ):
            payload, operation = client.search()
        self.assertEqual(payload["items"], [])
        self.assertTrue(operation["empty_result"])

        with patch.object(client, "_request_json", return_value={"status": "ok"}):
            with self.assertRaisesRegex(UmaMoeError, "sans records"):
                client.search()

    def test_transient_http_failure_retries_with_bounded_retry_after(self) -> None:
        logs: list[str] = []
        client = UmaMoeApiClient(
            "https://example.invalid/api",
            logger=logs.append,
            max_retries=1,
            retry_backoff=0.25,
            max_retry_delay=1.5,
        )
        errors = [
            urllib.error.HTTPError(
                "https://example.invalid/api/v3/search",
                503,
                "unavailable",
                {"Retry-After": "30"},
                io.BytesIO(b"down"),
            ),
            urllib.error.HTTPError(
                "https://example.invalid/api/v3/search",
                503,
                "unavailable",
                {},
                io.BytesIO(b"down"),
            ),
        ]
        with (
            patch("uma_moe.urllib.request.urlopen", side_effect=errors) as request,
            patch("uma_moe.time.sleep") as sleep,
        ):
            with self.assertRaises(UmaMoeError):
                client._request_document("https://example.invalid/api/v3/search")
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(1.5)
        self.assertTrue(any("HTTP 503" in message for message in logs))

    def test_documented_parent_filters_use_only_fixed_parameter_names(self) -> None:
        client = UmaMoeApiClient("https://example.invalid/api")
        spec = {
            "paths": {
                "/api/v3/search": {
                    "get": {
                        "parameters": [
                            {"name": "main_parent_id"},
                            {"name": "exclude_main_parent_id"},
                            {
                                "name": "parent_costume_whitelist_guess",
                                "description": "Allowed parent costume cards",
                            },
                        ]
                    }
                }
            }
        }
        with patch.object(client, "discover_openapi", return_value=(spec, "spec")):
            keys = client.documented_parent_card_filter_keys()
        self.assertEqual(
            keys,
            {
                "allowed": "main_parent_id",
                "excluded": "exclude_main_parent_id",
            },
        )

    def test_api_soft_white_filter_is_capped_at_top_sixteen(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            weights = root / "weights.json"
            catalog = root / "catalog.json"
            skills = {
                f"skill_{index}": {
                    "spark_name": f"Skill {index}",
                    "weight_matrix": {
                        "turf": {
                            "mile": {
                                "late_surger": {"weight": 1.0 - index / 100.0}
                            }
                        }
                    },
                }
                for index in range(24)
            }
            weights.write_text(json.dumps({"skills": skills}), encoding="utf-8")
            catalog.write_text(json.dumps({"skills": []}), encoding="utf-8")
            captured: list[list[str]] = []

            def resolve(_master: object, names: list[str]) -> list[int]:
                captured.append(list(names))
                return list(range(len(names)))

            with patch("uma_moe.resolve_white_factor_group_ids", side_effect=resolve):
                uql, metadata = generate_auto_uql(
                    weights,
                    catalog,
                    surface="turf",
                    distance="mile",
                    style="late_surger",
                    master_path="master.mdb",
                )

        self.assertEqual(len(captured[0]), 16)
        self.assertEqual(len(metadata["search_filters"]["optional_main_white_factors"]), 16)
        self.assertIn("Skill 23", uql)

    def test_quality_thresholds_use_documented_api_parameters(self) -> None:
        _uql, metadata = self._generate(
            {
                "min_blue_stars_sum": 7,
                "min_white_count": 12,
                "min_white_stars_sum": 20,
            }
        )

        expected = {
            "min_blue_stars_sum": 7,
            "min_white_count": 12,
            "min_white_stars_sum": 20,
        }
        self.assertEqual(metadata["quality_filters"], expected)
        for key, value in expected.items():
            self.assertEqual(metadata["search_filters"][key], value)

    def test_zero_quality_thresholds_are_not_sent(self) -> None:
        _uql, metadata = self._generate(
            {
                "min_blue_stars_sum": 0,
                "min_white_count": 0,
                "min_white_stars_sum": 0,
            }
        )

        self.assertEqual(metadata["quality_filters"], {})
        self.assertNotIn("min_blue_stars_sum", metadata["search_filters"])
        self.assertNotIn("min_white_count", metadata["search_filters"])
        self.assertNotIn("min_white_stars_sum", metadata["search_filters"])

    def test_quality_thresholds_are_preserved_across_planned_cohorts(self) -> None:
        class RecordingClient(UmaMoeApiClient):
            def __init__(self) -> None:
                super().__init__("https://example.invalid/api")
                self.seen_filters: list[dict[str, object]] = []

            def search_many(  # type: ignore[override]
                self, *, filters=None, desired_candidates=250, page_size=100, logger=None
            ):
                self.seen_filters.append(dict(filters or {}))
                return {"items": []}, {"filters": dict(filters or {})}

        client = RecordingClient()
        client.search_many_planned(
            base_filters={"min_blue_stars_sum": 7, "min_white_count": 12},
            retrieval_plan={
                "cohorts": [
                    {
                        "name": "distance",
                        "kind": "distance",
                        "share": 0.5,
                        "filters": {"pink_sparks": [3203]},
                    },
                    {"name": "large", "kind": "broad", "share": 0.5, "filters": {}},
                ]
            },
            desired_candidates=100,
        )

        self.assertGreaterEqual(len(client.seen_filters), 1)
        for filters in client.seen_filters:
            self.assertEqual(filters["min_blue_stars_sum"], 7)
            self.assertEqual(filters["min_white_count"], 12)

    def test_named_lineage_minimum_becomes_api_aggregate_id_range(self) -> None:
        resolver = SimpleNamespace(
            factors={
                201: {
                    "factor_id": 201,
                    "type": "blue_stat",
                    "name": "Stamina",
                },
                202: {
                    "factor_id": 202,
                    "type": "blue_stat",
                    "name": "Stamina",
                },
                1201: {
                    "factor_id": 1201,
                    "type": "red_aptitude",
                    "name": "Dirt",
                },
            },
            close=lambda: None,
        )
        with patch("uma_moe.MasterResolver", return_value=resolver):
            filters, diagnostics = build_lineage_factor_api_filters(
                "master.mdb",
                ("Stamina", 5),
                ("Dirt", 4),
            )

        self.assertEqual(filters["blue_sparks"], [205, 206, 207, 208, 209])
        self.assertEqual(
            filters["pink_sparks"],
            [1204, 1205, 1206, 1207, 1208, 1209],
        )
        self.assertTrue(diagnostics["blue_sparks"]["server_side"])
        self.assertTrue(diagnostics["blue_sparks"]["locally_revalidated"])

    def test_hard_lineage_filter_suppresses_conflicting_soft_cohort(self) -> None:
        class RecordingClient(UmaMoeApiClient):
            def __init__(self) -> None:
                super().__init__("https://example.invalid/api")
                self.seen_filters: list[dict[str, object]] = []

            def search_many(  # type: ignore[override]
                self, *, filters=None, desired_candidates=250, page_size=100, logger=None
            ):
                self.seen_filters.append(dict(filters or {}))
                return {"items": []}, {"filters": dict(filters or {})}

        client = RecordingClient()
        _payload, operation = client.search_many_planned(
            base_filters={"pink_sparks": [1205, 1206, 1207, 1208, 1209]},
            retrieval_plan={
                "cohorts": [
                    {
                        "name": "distance",
                        "kind": "distance",
                        "share": 0.45,
                        "filters": {"pink_sparks": [3203, 3204]},
                    },
                    {
                        "name": "large",
                        "kind": "broad",
                        "share": 0.55,
                        "filters": {},
                    },
                ]
            },
            desired_candidates=100,
        )

        self.assertEqual(
            client.seen_filters,
            [{"pink_sparks": [1205, 1206, 1207, 1208, 1209]}],
        )
        suppressed = operation["retrieval_plan"]["suppressed_conflicting_cohorts"]
        self.assertEqual(suppressed[0]["kind"], "distance")
        self.assertEqual(suppressed[0]["conflicting_keys"], ["pink_sparks"])


if __name__ == "__main__":
    unittest.main()

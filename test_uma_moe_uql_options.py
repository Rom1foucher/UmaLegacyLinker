from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from uma_moe import UmaMoeApiClient, generate_auto_uql


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


if __name__ == "__main__":
    unittest.main()

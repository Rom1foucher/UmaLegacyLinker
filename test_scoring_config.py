from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scoring_config import (
    ScoringConfigError,
    build_overrides,
    deep_merge,
    load_effective_scoring_config,
    materialize_effective_scoring_config,
    read_json_object,
    validate_scoring_config,
    validate_skill_priorities_config,
    write_json_object,
)
from uma_moe import MAX_FETCH_CANDIDATES, UmaMoeApiClient


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SCORING = PROJECT_DIR / "default_parent_scoring.json"
DEFAULT_SKILL_PRIORITIES = PROJECT_DIR / "default_skill_priorities.json"


class ScoringConfigTests(unittest.TestCase):
    def test_default_profile_is_valid(self) -> None:
        default, overrides, effective = load_effective_scoring_config(DEFAULT_SCORING)
        self.assertEqual(overrides, {})
        self.assertEqual(default, effective)
        validate_scoring_config(effective)

    def test_minimal_overrides_round_trip(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        current = deep_merge(
            default,
            {
                "blue_stat_weights_by_distance": {"long": {"Stamina": 2.5}},
                "pink_dimension_weights": {"style": 0.9},
            },
        )
        overrides = build_overrides(default, current)
        self.assertEqual(overrides["blue_stat_weights_by_distance"]["long"]["Stamina"], 2.5)
        self.assertEqual(overrides["pink_dimension_weights"]["style"], 0.9)
        self.assertNotIn("mode_weights", overrides)

        with tempfile.TemporaryDirectory() as directory:
            override_path = Path(directory) / "overrides.json"
            effective_path = Path(directory) / "effective.json"
            write_json_object(override_path, overrides)
            materialize_effective_scoring_config(DEFAULT_SCORING, override_path, effective_path)
            reloaded = read_json_object(effective_path)
        self.assertEqual(reloaded, current)

    def test_negative_weight_is_rejected(self) -> None:
        default = read_json_object(DEFAULT_SCORING)
        invalid = deep_merge(default, {"pink_dimension_weights": {"distance": -1}})
        with self.assertRaises(ScoringConfigError):
            validate_scoring_config(invalid)

    def test_default_white_skill_priorities_are_valid(self) -> None:
        validate_skill_priorities_config(read_json_object(DEFAULT_SKILL_PRIORITIES))


class FakeUmaMoeClient(UmaMoeApiClient):
    def __init__(self) -> None:
        super().__init__("https://example.invalid/api")
        self.requested_pages: list[int] = []

    def search(self, *, filters=None, limit: int = 100, page: int = 0):  # type: ignore[override]
        self.requested_pages.append(page)
        items = [
            {"inheritance": {"inheritance_id": page * limit + index + 1}}
            for index in range(limit)
        ]
        return {"items": items, "total_pages": 100}, {
            "method": "GET",
            "path": "/api/v3/search",
            "page": page,
            "limit": limit,
        }


class UmaMoeFetchLimitTests(unittest.TestCase):
    def test_search_many_hard_caps_at_2000_candidates(self) -> None:
        client = FakeUmaMoeClient()
        payload, operation = client.search_many(desired_candidates=5000, page_size=100)
        self.assertEqual(len(payload["items"]), MAX_FETCH_CANDIDATES)
        self.assertEqual(operation["requested_candidates"], MAX_FETCH_CANDIDATES)
        self.assertEqual(len(client.requested_pages), 20)


if __name__ == "__main__":
    unittest.main()

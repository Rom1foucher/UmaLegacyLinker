from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from course_presets import (
    course_preset_conditions,
    load_course_preset_payload,
    normalize_racecourse_name,
    ordered_course_presets,
    racecourse_names_match,
    resolve_course_overrides_path,
)
from manual_weights import generate_manual_skill_weights
from transfer_helper import _build_profile_contexts


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PRESETS = PROJECT_DIR / "default_course_overrides.json"


class CoursePresetTests(unittest.TestCase):
    def test_stale_saved_path_falls_back_to_bundled_file(self) -> None:
        resolved = resolve_course_overrides_path(
            PROJECT_DIR / "old-install" / "default_course_overrides.json",
            DEFAULT_PRESETS,
        )
        self.assertEqual(resolved, DEFAULT_PRESETS.resolve())

    def test_valid_custom_file_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            custom = Path(temp_dir) / "custom.json"
            custom.write_text('{"courses": {}}', encoding="utf-8")
            resolved = resolve_course_overrides_path(custom, DEFAULT_PRESETS)
            self.assertEqual(resolved, custom.resolve())

    def test_bundled_catalog_contains_all_expected_profiles(self) -> None:
        payload = load_course_preset_payload(DEFAULT_PRESETS)
        courses = payload["courses"]
        self.assertEqual(len(courses), 43)
        self.assertTrue(any(key.startswith("cm16_") for key in courses))
        self.assertTrue(any(key.startswith("cm46_") for key in courses))
        self.assertIn("team_trials_turf_long", courses)
        self.assertIn("team_trials_dirt_mile", courses)

    def test_display_order_prioritizes_future_cms_then_team_trials(self) -> None:
        payload = load_course_preset_payload(DEFAULT_PRESETS)
        ordered = ordered_course_presets(payload)
        keys = [key for key, _course in ordered]
        self.assertTrue(keys[0].startswith("cm16_"))
        self.assertTrue(keys[30].startswith("cm46_"))
        self.assertEqual(keys[31], "team_trials_turf_sprint")
        self.assertTrue(keys[-1].startswith("cm9_"))

    def test_exact_cm_conditions_are_canonical(self) -> None:
        payload = load_course_preset_payload(DEFAULT_PRESETS)
        course = next(
            course for key, course in payload["courses"].items() if key.startswith("cm22_")
        )
        self.assertEqual(
            course_preset_conditions(course),
            {
                "rotation": 2,
                "season": 4,
                "weather": 4,
                "ground_condition": 3,
            },
        )

    def test_ooi_preset_matches_ohi_mdb_label(self) -> None:
        self.assertEqual(normalize_racecourse_name("Ooi"), "ohi")
        self.assertEqual(normalize_racecourse_name("Ohi (10009)"), "ohi")
        self.assertTrue(racecourse_names_match("Ooi", "Ohi (10009)"))

    def test_transfer_helper_uses_only_five_next_cms_and_team_trials(self) -> None:
        payload = load_course_preset_payload(DEFAULT_PRESETS)
        contexts = _build_profile_contexts(payload, include_course_presets=True)
        course_keys = list(dict.fromkeys(context.course_key for context in contexts))

        self.assertEqual(len(contexts), 40)
        self.assertEqual(
            course_keys[:5],
            [
                "cm16_nakayama_1200_turf",
                "cm17_ooi_2000_dirt",
                "cm18_hanshin_1600_turf",
                "cm19_kyoto_2200_turf",
                "cm20_nakayama_2500_turf",
            ],
        )
        self.assertEqual(
            course_keys[5:],
            [
                "team_trials_turf_sprint",
                "team_trials_turf_mile",
                "team_trials_turf_medium",
                "team_trials_turf_long",
                "team_trials_dirt_mile",
            ],
        )
        self.assertFalse(any(context.key.startswith("generic:") for context in contexts))
        self.assertFalse(any(context.key.startswith("course:cm21_") for context in contexts))
        cm17 = next(context for context in contexts if context.key.startswith("course:cm17_"))
        self.assertEqual(cm17.course_conditions["ground_condition"], 2)


class ManualWeightsCourseMetadataTests(unittest.TestCase):
    def test_generated_course_weights_preserve_conditions_and_category(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog = root / "skills.json"
            priorities = root / "priorities.json"
            courses = root / "courses.json"
            catalog.write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "skill_id": 1,
                                "description": "test",
                                "white_spark": {
                                    "catalog_key": "test_skill",
                                    "spark_name": "Test Skill",
                                    "factor_group_id": 1,
                                    "factor_ids_by_stars": {"1": 1},
                                },
                                "profile_hints": {},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            priorities.write_text(
                json.dumps({"default_weight": 0.1, "skills": {}}), encoding="utf-8"
            )
            courses.write_text(
                json.dumps(
                    {
                        "courses": {
                            "cm_test": {
                                "label": "CM Test",
                                "category": "champions_meeting_upcoming",
                                "sequence": 99,
                                "profile": {"surface": "turf", "distance": "mile"},
                                "race": {"racecourse": "Tokyo"},
                                "conditions": {"rotation": 2, "season": [1, 5]},
                                "skills": {},
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            result = generate_manual_skill_weights(
                catalog, priorities, root / "output", courses
            )
            generated = json.loads(result.course_weights_path.read_text(encoding="utf-8"))
            course = generated["courses"]["cm_test"]
            self.assertEqual(course["category"], "champions_meeting_upcoming")
            self.assertEqual(course["sequence"], 99)
            self.assertEqual(course["conditions"], {"rotation": 2, "season": [1, 5]})


if __name__ == "__main__":
    unittest.main()

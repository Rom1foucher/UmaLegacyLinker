"""Regression coverage for the standalone headless entry point."""

from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cli


class CliWorkflowTests(unittest.TestCase):
    def _args(self, output: Path, **overrides: object) -> Namespace:
        values: dict[str, object] = {
            "master": "master.mdb",
            "json": "data.json",
            "output": str(output),
            "catalog_only": False,
            "umalator_batch": None,
            "course_overrides": None,
            "rank_parents": False,
            "transfer_helper": False,
            "ace_card_id": 100101,
            "future_parent_card_id": 100201,
            "track_id": None,
            "rotation": None,
            "season": None,
            "weather": None,
            "ground_condition": None,
            "surface": "turf",
            "distance": "medium",
            "style": "pace_chaser",
            "course_key": None,
            "scoring_config": None,
            "skill_priorities": None,
            "top": 5,
        }
        values.update(overrides)
        return Namespace(**values)

    @staticmethod
    def _linked(output: Path) -> SimpleNamespace:
        return SimpleNamespace(
            json_path=output / "veterans.json",
            skills_catalog_path=output / "skills.json",
            race_factor_skills_path=output / "race_factors.json",
        )

    @staticmethod
    def _weights(output: Path) -> SimpleNamespace:
        return SimpleNamespace(
            weights_path=output / "manual_weights.json",
            course_weights_path=output / "course_weights.json",
        )

    def test_rank_parents_prepares_configs_and_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            overrides = output / "overrides.json"
            overrides.write_text("{}\n", encoding="utf-8")
            result = SimpleNamespace(
                rankings_json_path=output / "rankings.json",
                parent_pairs_csv_path=output / "pairs.csv",
                future_grandparents_csv_path=output / "future_gp.csv",
            )
            args = self._args(
                output,
                rank_parents=True,
                scoring_config=str(overrides),
                skill_priorities=str(overrides),
            )

            with (
                patch.object(cli, "link_veterans", return_value=self._linked(output)),
                patch.object(
                    cli,
                    "generate_manual_skill_weights",
                    return_value=self._weights(output),
                ),
                patch.object(cli, "optimize_parents", return_value=result) as optimize,
            ):
                self.assertEqual(cli.run_cli(args), 0)

            self.assertTrue((output / "active_skill_priorities.json").is_file())
            self.assertTrue((output / "active_parent_scoring.json").is_file())
            optimize.assert_called_once()

    def test_transfer_helper_prepares_configs_and_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            overrides = output / "overrides.json"
            overrides.write_text("{}\n", encoding="utf-8")
            result = SimpleNamespace(
                report_json_path=output / "report.json",
                candidates_csv_path=output / "candidates.csv",
                summary_txt_path=output / "summary.txt",
                safe_transfer_count=1,
                review_count=2,
                likely_keep_count=3,
                keep_count=4,
            )
            args = self._args(
                output,
                transfer_helper=True,
                scoring_config=str(overrides),
                skill_priorities=str(overrides),
            )

            with (
                patch.object(cli, "link_veterans", return_value=self._linked(output)),
                patch.object(
                    cli,
                    "generate_manual_skill_weights",
                    return_value=self._weights(output),
                ),
                patch.object(
                    cli,
                    "analyze_transfer_candidates",
                    return_value=result,
                ) as analyze,
            ):
                self.assertEqual(cli.run_cli(args), 0)

            self.assertTrue((output / "active_skill_priorities.json").is_file())
            self.assertTrue((output / "active_parent_scoring.json").is_file())
            analyze.assert_called_once()


if __name__ == "__main__":
    unittest.main()

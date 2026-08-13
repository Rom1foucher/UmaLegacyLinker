from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from loop_engine import (
    LoopEngineError,
    analyze_outcome,
    analyze_transition,
    add_manual_run,
    build_run_result,
    build_target_options,
    close_transition,
    complete_transition,
    configure_draft,
    detect_transition_runs,
    factor_key,
    generation_probability,
    rank_parent_candidates,
    rank_parent_pairs,
    record_plan,
    record_run_verdict,
    snapshot_member,
    transition_statistics,
)
from loop_models import LoopProject, LoopSkillTarget
from loop_repository import LoopProjectRepository, LoopRepositoryError
from transfer_helper import _manual_protection

PROJECT_DIR = Path(__file__).resolve().parents[1]


def white(group_id: int, name: str = "Uma Stan", stars: int = 2) -> dict[str, object]:
    return {
        "factor_id": group_id * 100 + stars,
        "factor_group_id": group_id,
        "name": name,
        "stars": stars,
        "type": "white_skill",
    }


def pink(name: str, stars: int = 3) -> dict[str, object]:
    return {
        "factor_id": 900000 + stars,
        "name": name,
        "stars": stars,
        "type": "red_aptitude",
    }


def member(
    trained_id: int,
    chara_id: int,
    name: str,
    *,
    factors: list[dict[str, object]] | None = None,
    gp1: dict[str, object] | None = None,
    gp2: dict[str, object] | None = None,
) -> dict[str, object]:
    own = list(factors or [])
    return {
        "trained_chara_id": trained_id,
        "card_id": chara_id * 100,
        "chara_id": chara_id,
        "uma_name": name,
        "card_name": name,
        "factors": {
            "all": own,
            "by_type": {
                "white_skill": [factor for factor in own if factor.get("type") == "white_skill"],
                "red_aptitude": [factor for factor in own if factor.get("type") == "red_aptitude"],
            },
        },
        "g1_wins": {"names": [], "details": []},
        "when_used_as_parent": {
            "grandparent_1": gp1,
            "grandparent_2": gp2,
        },
    }


def parent_snapshot(source: dict[str, object]) -> dict[str, object]:
    return {
        **source,
        "local_trained_chara_id": source["trained_chara_id"],
    }


class LoopWorkshopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = LoopSkillTarget(
            key="white_skill:group:42",
            name="Uma Stan",
            factor_group_id=42,
            policy="static",
            learned_form="normal",
            acquisition_probability=0.80,
        )
        gp1 = member(11, 11, "GP 1", factors=[white(42, stars=1)])
        gp2 = member(12, 12, "GP 2", factors=[white(42, stars=2)])
        gp3 = member(21, 21, "GP 3", factors=[white(42, stars=3)])
        gp4 = member(22, 22, "GP 4", factors=[white(42, stars=2)])
        self.parent_1 = member(
            1,
            1,
            "Parent 1",
            factors=[white(42, stars=3)],
            gp1=gp1,
            gp2=gp2,
        )
        self.parent_2 = member(
            2,
            2,
            "Parent 2",
            factors=[white(42, stars=2)],
            gp1=gp3,
            gp2=gp4,
        )
        self.trainee = {
            "card_id": 300,
            "chara_id": 3,
            "uma_name": "Trainee",
            "card_name": "Trainee",
        }

    def test_generation_table_keeps_acquisition_and_generation_distinct(self) -> None:
        self.assertAlmostEqual(generation_probability("normal", 0), 0.20)
        self.assertAlmostEqual(generation_probability("normal", 6), 0.35)
        self.assertAlmostEqual(generation_probability("circle", 6), 0.40)
        self.assertAlmostEqual(generation_probability("gold", 6), 0.70)

        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
            quality_band="ss_to_ue_plus",
        )
        row = plan["skills"][0]
        self.assertEqual(row["input_coverage"], 6)
        self.assertEqual(row["input_star_sum"], 13)
        self.assertAlmostEqual(row["generation_probability_conditional"], 0.35)
        self.assertAlmostEqual(row["generation_probability_full"], 0.28)
        self.assertAlmostEqual(row["probability_two_plus_full"], 0.224)
        self.assertEqual(row["output_coverage_if_miss"], 2)
        self.assertEqual(row["output_coverage_if_hit"], 3)

    def test_exact_factor_groups_do_not_collapse_equal_names(self) -> None:
        left = white(42, "Repeated Name")
        right = white(43, "Repeated Name")
        self.assertNotEqual(factor_key(left), factor_key(right))
        options = build_target_options(
            [member(1, 1, "Carrier", factors=[left, right])]
        )
        self.assertEqual({option.factor_group_id for option in options}, {42, 43})
        target = LoopSkillTarget(
            key="white_skill:group:42",
            name="Repeated Name",
            factor_group_id=42,
        )
        wrong_group = member(4, 4, "Wrong", factors=[right])
        empty_parent = member(5, 5, "Empty")
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=wrong_group,
            parent_2=empty_parent,
            targets=[target],
        )
        self.assertEqual(plan["skills"][0]["input_coverage"], 0)

    def test_outcome_checks_parent_provenance_and_own_factor(self) -> None:
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
        )
        outcome = member(
            99,
            3,
            "Descendant",
            factors=[white(42, stars=3)],
            gp1=parent_snapshot(self.parent_1),
            gp2=parent_snapshot(self.parent_2),
        )
        analysis = analyze_outcome(outcome=outcome, plan=plan)
        self.assertEqual(analysis["parent_provenance"], "match")
        self.assertTrue(analysis["hard_targets_met"])
        self.assertEqual(analysis["skills"][0]["output_coverage"], 3)
        self.assertEqual(analysis["suggested_verdict"], "promote_core")

    def test_outcome_uses_snapshots_when_umadump_has_no_parent_ids(self) -> None:
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
        )
        snapshot_1 = dict(self.parent_1)
        snapshot_1.pop("trained_chara_id", None)
        snapshot_2 = dict(self.parent_2)
        snapshot_2.pop("trained_chara_id", None)
        outcome = member(
            99,
            3,
            "Descendant",
            factors=[white(42, stars=2)],
            gp1=snapshot_1,
            gp2=snapshot_2,
        )
        analysis = analyze_outcome(outcome=outcome, plan=plan)
        self.assertEqual(analysis["parent_provenance"], "match_snapshot")
        self.assertEqual(analysis["trainee_provenance"], "match")

    def test_project_round_trip_and_transfer_protection(self) -> None:
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
        )
        project = LoopProject.create("Backline core")
        project.targets = [self.target]
        transition = record_plan(
            project,
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            plan=plan,
        )
        self.assertEqual(project.active_trained_ids(), {1, 2})
        project.surface = "turf"
        project.distance = "mile"
        project.style = "late_surger"

        outcome = member(
            99,
            3,
            "Descendant",
            factors=[white(42, stars=2)],
            gp1=parent_snapshot(self.parent_1),
            gp2=parent_snapshot(self.parent_2),
        )
        analysis = analyze_outcome(outcome=outcome, plan=plan)
        complete_transition(
            project,
            transition_id=transition.transition_id,
            outcome=outcome,
            analysis=analysis,
            verdict="replace_core",
            replaces_trained_chara_id=1,
        )
        self.assertEqual(project.active_trained_ids(), {2, 99})

        second_outcome = member(100, 4, "Second descendant")
        second_trainee = {**self.trainee, "card_id": 400, "chara_id": 4}
        second_plan = analyze_transition(
            trainee=second_trainee,
            parent_1=self.parent_2,
            parent_2=outcome,
            targets=[self.target],
        )
        second_transition = record_plan(
            project,
            trainee=second_trainee,
            parent_1=self.parent_2,
            parent_2=outcome,
            plan=second_plan,
        )
        with self.assertRaises(LoopEngineError):
            complete_transition(
                project,
                transition_id=second_transition.transition_id,
                outcome=second_outcome,
                analysis={},
                verdict="replace_core",
                replaces_trained_chara_id=12345,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "white_loop_projects.json"
            repository = LoopProjectRepository(path)
            repository.save([project])
            loaded = repository.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "Backline core")
            self.assertEqual(
                (loaded[0].surface, loaded[0].distance, loaded[0].style),
                ("turf", "mile", "late_surger"),
            )
            self.assertEqual(repository.active_trained_ids(), {2, 99})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)

        self.assertEqual(
            _manual_protection({"active_loop_project": True}),
            ["active_loop_project"],
        )


    def test_draft_round_trip_survives_reboot_without_starting_batch(self) -> None:
        project = LoopProject.create("Draft survives")
        project.targets = [self.target]
        draft = configure_draft(
            project,
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            last_plan=None,
        )
        self.assertIsNotNone(draft)
        self.assertEqual(project.transitions, [])
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = LoopProjectRepository(Path(temp_dir) / "white_loop_projects.json")
            repository.save([project])
            loaded = repository.load()[0]
        self.assertIsNotNone(loaded.draft)
        self.assertEqual(loaded.draft.trainee_card_id, self.trainee["card_id"])
        self.assertEqual(loaded.draft.parent_1_trained_id, 1)
        self.assertEqual(loaded.draft.parent_2_trained_id, 2)
        self.assertEqual(loaded.transitions, [])

    def test_schema_v1_is_read_and_migrated_on_save(self) -> None:
        project = LoopProject.create("Legacy")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "white_loop_projects.json"
            path.write_text(
                json.dumps({"schema_version": 1, "projects": [project.to_dict()]}),
                encoding="utf-8",
            )
            repository = LoopProjectRepository(path)
            loaded = repository.load()
            self.assertEqual(len(loaded), 1)
            repository.save(loaded)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 2)

    def test_batch_auto_detection_deduplicates_and_documents_acquisition(self) -> None:
        target = LoopSkillTarget(
            key="white_skill:group:42",
            name="Uma Stan",
            factor_group_id=42,
            skill_id=42001,
            policy="static",
        )
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[target],
        )
        project = LoopProject.create("Batch")
        project.targets = [target]
        transition = record_plan(
            project,
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            plan=plan,
            baseline_trained_ids=[1, 2, 50],
        )
        outcome = member(
            99,
            3,
            "Descendant",
            factors=[white(42, stars=2)],
            gp1=parent_snapshot(self.parent_1),
            gp2=parent_snapshot(self.parent_2),
        )
        outcome["learned_skills"] = [
            {
                "skill_id": 42999,
                "group_id": 42,
                "name": "Uma Stan ◎",
                "form": "double_circle",
                "level": 1,
            }
        ]
        wrong_costume = member(100, 4, "Wrong costume", gp1=parent_snapshot(self.parent_1), gp2=parent_snapshot(self.parent_2))
        detected = detect_transition_runs(project, [self.parent_1, self.parent_2, outcome, wrong_costume])
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0][1].trained_chara_id, 99)
        self.assertTrue(detected[0][1].auto_detected)
        row = detected[0][1].analysis["skills"][0]
        self.assertTrue(row["skill_acquired"])
        self.assertEqual(row["acquired_form"], "double_circle")
        self.assertTrue(row["factor_generated"])
        self.assertEqual(row["factor_stars"], 2)
        # Same linked collection is safe to scan repeatedly.
        self.assertEqual(detect_transition_runs(project, [outcome, wrong_costume]), [])
        stats = transition_statistics(transition)
        self.assertEqual(stats["run_count"], 1)
        target_stats = stats["target_stats"][0]
        self.assertEqual(target_stats["acquired_form_counts"]["double_circle"], 1)
        self.assertEqual(target_stats["factor_generated_count"], 1)
        self.assertEqual(target_stats["factor_two_plus_count"], 1)
        self.assertAlmostEqual(target_stats["theoretical_generation_conditional"], 0.40)

    def test_missing_learned_skill_payload_keeps_acquisition_unknown(self) -> None:
        target = LoopSkillTarget(
            key="white_skill:group:42",
            name="Target",
            factor_group_id=42,
            skill_id=4202,
        )
        outcome = member(77, 7, "Outcome")
        outcome["learned_skills"] = []
        outcome["learned_skills_known"] = False
        outcome["factors"]["all"].append(white(42, "Target", 2))
        outcome["factors"]["by_type"]["white_skill"].append(white(42, "Target", 2))
        plan = {
            "trainee": {"card_id": outcome["card_id"], "chara_id": outcome["chara_id"]},
            "parents": {
                "parent_1": snapshot_member(self.parent_1),
                "parent_2": snapshot_member(self.parent_2),
            },
            "targets": [target.to_dict()],
        }
        outcome["when_used_as_parent"] = {
            "grandparent_1": snapshot_member(self.parent_1),
            "grandparent_2": snapshot_member(self.parent_2),
        }
        run = build_run_result(outcome=outcome, plan=plan)
        self.assertFalse(run.learned_skills_known)
        self.assertIsNone(run.analysis["skills"][0]["skill_acquired"])
        self.assertTrue(run.analysis["skills"][0]["factor_generated"])

    def test_reviewing_run_does_not_close_batch(self) -> None:
        plan = analyze_transition(
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
        )
        project = LoopProject.create("Batch lifecycle")
        transition = record_plan(
            project,
            trainee=self.trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            plan=plan,
            baseline_trained_ids=[1, 2],
        )
        outcome = member(
            99,
            3,
            "Descendant",
            factors=[white(42, stars=2)],
            gp1=parent_snapshot(self.parent_1),
            gp2=parent_snapshot(self.parent_2),
        )
        run = add_manual_run(project, transition_id=transition.transition_id, outcome=outcome)
        record_run_verdict(
            project,
            transition_id=transition.transition_id,
            trained_chara_id=run.trained_chara_id,
            verdict="keep_side",
            branch="custom",
        )
        self.assertEqual(transition.status, "pending")
        self.assertTrue(transition.active)
        self.assertEqual(transition.runs[0].verdict, "keep_side")
        with self.assertRaises(LoopEngineError):
            record_run_verdict(
                project,
                transition_id=transition.transition_id,
                trained_chara_id=outcome["trained_chara_id"],
                verdict="ignore",
            )
        close_transition(project, transition_id=transition.transition_id)
        self.assertEqual(transition.status, "completed")

    def test_parent_ranking_prefers_target_coverage_and_recommends_pair(self) -> None:
        self.parent_1["rank"] = "UG2"
        self.parent_1["rank_score"] = 19_842
        third = member(3, 3, "Parent 3")
        candidates = rank_parent_candidates(
            [third, self.parent_2, self.parent_1],
            [self.target],
            limit=3,
        )
        self.assertEqual([row["trained_chara_id"] for row in candidates], [1, 2, 3])
        self.assertEqual(candidates[0]["direct_hits"], 1)
        self.assertEqual(candidates[0]["static_hits"], 1)
        self.assertEqual(candidates[0]["rank"], "UG2")
        self.assertEqual(candidates[0]["rank_score"], 19_842)
        pairs = rank_parent_pairs(
            [third, self.parent_2, self.parent_1],
            [self.target],
            trainee=self.trainee,
            limit=2,
        )
        self.assertEqual(
            {pairs[0]["parent_1_trained_id"], pairs[0]["parent_2_trained_id"]},
            {1, 2},
        )
        self.assertEqual(pairs[0]["lineage_coverage"], 6)
        self.assertEqual(pairs[0]["parent_1_in_game_score"], 19_842)

    def test_pair_ranking_and_g1_plan_use_inherited_aptitudes(self) -> None:
        self.parent_1["factors"]["all"].append(pink("Mile", 3))
        self.parent_1["factors"]["by_type"]["red_aptitude"].append(pink("Mile", 3))
        self.parent_2["factors"]["all"].append(pink("Turf", 3))
        self.parent_2["factors"]["by_type"]["red_aptitude"].append(pink("Turf", 3))
        trainee = {
            **self.trainee,
            "target_aptitudes": {
                "surface": {"rank": 6, "label": "B"},
                "distance": {"rank": 6, "label": "B"},
                "style": {"rank": 7, "label": "A"},
            },
            "training_aptitudes": {
                "surface": {
                    "turf": {"base_rank": 6, "initial_rank": 6},
                    "dirt": {"base_rank": 1, "initial_rank": 1},
                },
                "distance": {
                    "sprint": {"base_rank": 2, "initial_rank": 2},
                    "mile": {"base_rank": 6, "initial_rank": 6},
                    "medium": {"base_rank": 5, "initial_rank": 5},
                    "long": {"base_rank": 1, "initial_rank": 1},
                },
            },
        }
        config = json.loads(
            (PROJECT_DIR / "default_parent_scoring.json").read_text(encoding="utf-8")
        )
        pairs = rank_parent_pairs(
            [self.parent_1, self.parent_2],
            [self.target],
            trainee=trainee,
            surface="turf",
            distance="mile",
            style="late_surger",
            aptitude_config=config,
        )
        self.assertTrue(pairs[0]["aptitude"]["available"])
        self.assertEqual(pairs[0]["aptitude"]["distance"]["initial_rank_label"], "A")
        self.assertEqual(pairs[0]["aptitude"]["surface"]["initial_rank_label"], "A")
        self.assertNotEqual(pairs[0]["heuristic_score"], pairs[0]["white_score"])

        plan = analyze_transition(
            trainee=trainee,
            parent_1=self.parent_1,
            parent_2=self.parent_2,
            targets=[self.target],
        )
        training = plan["g1"]["training_aptitudes"]
        self.assertEqual(training["distance"]["mile"]["inherited_stars"], 3)
        self.assertEqual(training["distance"]["mile"]["initial_rank_label"], "A")
        self.assertEqual(training["surface"]["turf"]["initial_rank_label"], "A")
        self.assertEqual(plan["g1"]["win_probability_cutoff"], 0.60)

    def test_repository_deletes_only_requested_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = LoopProjectRepository(Path(temp_dir) / "projects.json")
            first = LoopProject.create("First")
            second = LoopProject.create("Second")
            repository.save([first, second])
            remaining = repository.delete(first.project_id)
            self.assertEqual([project.project_id for project in remaining], [second.project_id])
            self.assertEqual([project.name for project in repository.load()], ["Second"])
            with self.assertRaises(LoopRepositoryError):
                repository.delete(first.project_id)


if __name__ == "__main__":
    unittest.main()

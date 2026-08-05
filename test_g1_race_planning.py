import sqlite3
import tempfile
import unittest
from pathlib import Path

from g1_race_planning import (
    build_pair_g1_diagnostic,
    calendar_slots,
    optimize_race_schedule,
    schedule_export_summary,
    years_for_race_permissions,
)
from legacy_linker import MasterResolver
from parent_optimizer import AffinityResolver


def member(*races: dict) -> dict:
    return {
        "g1_wins": {
            "names": [race["name"] for race in races],
            "details": list(races),
        }
    }


def test_race_permission_mapping_matches_the_three_career_years() -> None:
    assert years_for_race_permissions([1]) == [1]
    assert years_for_race_permissions([2]) == [2]
    assert years_for_race_permissions([3]) == [2, 3]
    assert years_for_race_permissions([4]) == [3]
    assert years_for_race_permissions([1, 3, 5]) == [1, 2, 3]


def test_calendar_slots_use_early_and_late_half_months() -> None:
    assert calendar_slots(race_date=505, race_permissions=[2]) == [
        {"year": 2, "month": 5, "half": 1}
    ]
    assert calendar_slots(race_date=1028, race_permissions=[3]) == [
        {"year": 2, "month": 10, "half": 2},
        {"year": 3, "month": 10, "half": 2},
    ]
    assert calendar_slots(race_date=0, race_permissions=[1]) == []


def test_pair_diagnostic_keeps_shared_and_one_sided_races_with_details() -> None:
    shared_left = {
        "name": "Shared Cup",
        "race_id": 1022,
        "date": 1028,
        "race_permissions": [3],
        "schedule_slots": [
            {"year": 2, "month": 10, "half": 2},
            {"year": 3, "month": 10, "half": 2},
        ],
    }
    shared_right = {
        "name": "Shared Cup",
        "race_id": 1022,
        "schedule_slots": [{"year": 2, "month": 10, "half": 2}],
    }
    left = member(
        shared_left,
        {
            "name": "Left Stakes",
            "race_id": 1001,
            "schedule_slots": [{"year": 1, "month": 12, "half": 2}],
        },
    )
    right = member(
        shared_right,
        {
            "name": "Right Sho",
            "race_id": 1002,
            "schedule_slots": [{"year": 3, "month": 2, "half": 1}],
        },
    )

    result = build_pair_g1_diagnostic(
        left,
        right,
        left_label="parent_1",
        right_label="parent_2",
        bonus_per_link=3,
    )

    assert result["common_g1_names"] == ["Shared Cup"]
    assert result["left_only_g1_names"] == ["Left Stakes"]
    assert result["right_only_g1_names"] == ["Right Sho"]
    assert result["common_g1"][0]["affinity_bonus"] == 6
    assert result["left_only_g1"][0]["affinity_bonus"] == 3
    assert result["right_only_g1"][0]["affinity_bonus"] == 3
    assert result["common_g1"][0]["schedule_slots"] == [
        {"year": 2, "month": 10, "half": 2},
        {"year": 3, "month": 10, "half": 2},
    ]
    assert result["exact_bonus_if_all_won"] == 12
    assert result["optimal_bonus"] == 12
    assert result["optimal_race_count"] == 3
    assert result["scheduled_race_count"] == 3


def test_schedule_keeps_only_the_best_g1_when_a_turn_collides() -> None:
    races = [
        {
            "name": "Shared Cup",
            "affinity_bonus": 6,
            "schedule_slots": [{"year": 2, "month": 5, "half": 1}],
        },
        {
            "name": "Left Cup",
            "affinity_bonus": 3,
            "schedule_slots": [{"year": 2, "month": 5, "half": 1}],
        },
    ]

    result = optimize_race_schedule(races)

    assert result["optimal_bonus"] == 6
    assert result["optimal_race_count"] == 1
    assert result["lost_bonus"] == 3
    assert races[0]["planning_status"] == "scheduled"
    assert races[1]["planning_status"] == "calendar_conflict"
    assert races[0]["planned_slot"] == {"year": 2, "month": 5, "half": 1}


def test_schedule_moves_flexible_g1_to_avoid_three_and_four_race_streaks() -> None:
    races = [
        {
            "name": f"Fixed {phase}",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": phase // 2 + 1, "half": phase % 2 + 1}
            ],
        }
        for phase in (4, 5, 6)
    ]
    races.append(
        {
            "name": "Flexible",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": 4, "half": 2},
                {"year": 3, "month": 4, "half": 2},
            ],
        }
    )

    result = optimize_race_schedule(races)

    assert result["optimal_bonus"] == 12
    assert races[-1]["planned_slot"] == {"year": 3, "month": 4, "half": 2}
    assert result["streaks"]["max_consecutive"] == 3
    assert result["streaks"]["runs_of_4_plus"] == 0


def test_schedule_keeps_four_race_streak_but_marks_every_race_as_risky() -> None:
    races = [
        {
            "name": f"Fixed {phase}",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": phase // 2 + 1, "half": phase % 2 + 1}
            ],
        }
        for phase in (4, 5, 6, 7)
    ]

    result = optimize_race_schedule(races)

    assert result["optimal_bonus"] == 12
    assert result["optimal_race_count"] == 4
    assert result["streaks"]["max_consecutive"] == 4
    assert all(race["planning_status"] == "scheduled" for race in races)
    assert all(race["consecutive_race_count"] == 4 for race in races)
    assert all(race["long_streak_warning"] is True for race in races)


def test_schedule_never_places_two_g1_on_the_same_turn() -> None:
    races = [
        {
            "name": "Flexible A",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": 6, "half": 1},
                {"year": 3, "month": 6, "half": 1},
            ],
        },
        {
            "name": "Flexible B",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": 6, "half": 1},
                {"year": 3, "month": 6, "half": 1},
            ],
        },
        {
            "name": "Flexible C",
            "affinity_bonus": 3,
            "schedule_slots": [
                {"year": 2, "month": 6, "half": 1},
                {"year": 3, "month": 6, "half": 1},
            ],
        },
    ]

    result = optimize_race_schedule(races)
    planned = [
        tuple(race["planned_slot"].values())
        for race in races
        if race["planned_slot"] is not None
    ]

    assert len(planned) == len(set(planned)) == 2
    assert result["excluded_race_count"] == 1


def test_standard_plan_locks_objectives_and_trackblazer_ignores_them() -> None:
    slot = {"year": 2, "month": 5, "half": 2}
    shared = {
        "name": "Affinity Cup",
        "race_id": 1001,
        "schedule_slots": [slot],
    }
    result = build_pair_g1_diagnostic(
        member(shared),
        member(shared),
        left_label="Local parent",
        right_label="Remote parent",
        left_origin="local",
        right_origin="remote",
        objective_races=[
            {
                "name": "Mandatory Trial",
                "race_id": 2002,
                "objective_slot": slot,
                "schedule_slots": [slot],
                "mandatory_objective": True,
            }
        ],
    )

    standard = result["schedule_variants"]["standard"]
    trackblazer = result["schedule_variants"]["trackblazer"]
    standard_affinity = next(
        race for race in standard["races"] if race["name"] == "Affinity Cup"
    )

    assert standard["considers_objectives"] is True
    assert standard["optimal_bonus"] == 0
    assert standard["scheduled_objective_race_count"] == 1
    assert standard_affinity["planning_status"] == "objective_conflict"
    assert trackblazer["considers_objectives"] is False
    assert trackblazer["optimal_bonus"] == 6
    assert trackblazer["scheduled_objective_race_count"] == 0
    assert schedule_export_summary(result) == {
        "standard_optimal_bonus": 0,
        "trackblazer_optimal_bonus": 6,
        "objective_race_count": 1,
        "objective_conflict_count": 1,
    }


def test_g1_objective_is_merged_without_duplicate_affinity() -> None:
    normal_slot = {"year": 3, "month": 11, "half": 2}
    objective_slot = {"year": 2, "month": 11, "half": 2}
    g1 = {
        "name": "Same G1",
        "race_id": 1022,
        "schedule_slots": [objective_slot, normal_slot],
    }
    result = build_pair_g1_diagnostic(
        member(g1),
        {},
        left_label="Parent",
        right_label="Other",
        objective_races=[
            {
                "name": "Same G1",
                "race_id": 1022,
                "required_position": 1,
                "objective_slot": objective_slot,
                "schedule_slots": [objective_slot],
                "mandatory_objective": True,
            }
        ],
    )

    standard = result["schedule_variants"]["standard"]
    assert len(standard["races"]) == 1
    assert standard["optimal_bonus"] == 3
    assert standard["optimal_race_count"] == 1
    assert standard["races"][0]["mandatory_objective"] is True
    assert standard["races"][0]["objective_only"] is False
    assert standard["races"][0]["planned_slot"] == objective_slot


def test_one_sided_race_keeps_local_or_remote_provenance() -> None:
    left = member(
        {
            "name": "Local Stakes",
            "race_id": 1,
            "schedule_slots": [{"year": 2, "month": 3, "half": 1}],
        }
    )
    right = member(
        {
            "name": "Remote Sho",
            "race_id": 2,
            "schedule_slots": [{"year": 2, "month": 4, "half": 1}],
        }
    )
    result = build_pair_g1_diagnostic(
        left,
        right,
        left_label="Local",
        right_label="Remote",
        left_origin="local",
        right_origin="remote",
    )

    assert result["left_only_g1"][0]["source_origins"] == ["local"]
    assert result["right_only_g1"][0]["source_origins"] == ["remote"]


def test_streaks_do_not_cross_a_career_year_boundary() -> None:
    races = [
        {
            "name": "Junior finale",
            "affinity_bonus": 3,
            "schedule_slots": [{"year": 1, "month": 12, "half": 2}],
        },
        {
            "name": "Classic opener",
            "affinity_bonus": 3,
            "schedule_slots": [{"year": 2, "month": 1, "half": 1}],
        },
    ]

    result = optimize_race_schedule(races)

    assert result["streaks"]["max_consecutive"] == 1
    assert all(race["consecutive_race_count"] == 1 for race in races)


def test_master_resolver_enriches_g1_with_calendar_slots() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "master.mdb"
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE text_data (category INTEGER, "index" INTEGER, text TEXT);
            CREATE TABLE succession_factor (
                factor_id INTEGER, factor_group_id INTEGER, rarity INTEGER,
                factor_type INTEGER, effect_group_id INTEGER
            );
            CREATE TABLE succession_factor_effect (
                id INTEGER, factor_group_id INTEGER, effect_id INTEGER,
                target_type INTEGER, value_1 INTEGER, value_2 INTEGER
            );
            CREATE TABLE single_mode_wins_saddle (
                id INTEGER, win_saddle_type INTEGER,
                race_instance_id_1 INTEGER, race_instance_id_2 INTEGER,
                race_instance_id_3 INTEGER, race_instance_id_4 INTEGER,
                race_instance_id_5 INTEGER, race_instance_id_6 INTEGER,
                race_instance_id_7 INTEGER, race_instance_id_8 INTEGER
            );
            CREATE TABLE race_instance (id INTEGER, race_id INTEGER, date INTEGER);
            CREATE TABLE race (id INTEGER, grade INTEGER, "group" INTEGER);
            CREATE TABLE single_mode_program (
                id INTEGER, race_instance_id INTEGER, race_permission INTEGER
            );
            INSERT INTO text_data VALUES (28, 2001, 'Example G1');
            INSERT INTO text_data VALUES (147, 6003, 'Example Scenario');
            INSERT INTO succession_factor VALUES (6003, 600, 3, 6, 3);
            INSERT INTO succession_factor_effect VALUES (1, 600, 3, 2, 10, 30);
            INSERT INTO succession_factor_effect VALUES (2, 600, 3, 4, 10, 30);
            INSERT INTO race VALUES (1022, 100, 1);
            INSERT INTO race_instance VALUES (2001, 1022, 1028);
            INSERT INTO single_mode_program VALUES (1, 2001, 3);
            INSERT INTO single_mode_wins_saddle VALUES (
                88, 3, 2001, 0, 0, 0, 0, 0, 0, 0
            );
            """
        )
        connection.commit()
        connection.close()

        resolver = MasterResolver(path)
        try:
            resolved = resolver.resolve_g1_saddles([88])
            scenario_factor = resolver.factors[6003]
        finally:
            resolver.close()

    detail = resolved["details"][0]
    assert detail["race_id"] == 1022
    assert detail["date"] == 1028
    assert detail["years"] == [2, 3]
    assert scenario_factor["effects"] == [
        {"target_type": 2, "target_label": "stamina", "value_1": 10, "value_2": 30},
        {"target_type": 4, "target_label": "guts", "value_1": 10, "value_2": 30},
    ]
    assert detail["schedule_slots"] == [
        {"year": 2, "month": 10, "half": 2},
        {"year": 3, "month": 10, "half": 2},
    ]


def test_affinity_resolver_reads_only_fixed_race_objectives() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "master.mdb"
        connection = sqlite3.connect(path)
        connection.executescript(
            """
            CREATE TABLE succession_relation (
                relation_type INTEGER, relation_point INTEGER
            );
            CREATE TABLE succession_relation_member (
                relation_type INTEGER, chara_id INTEGER
            );
            CREATE TABLE card_data (id INTEGER, chara_id INTEGER);
            CREATE TABLE card_rarity_data (card_id INTEGER);
            CREATE TABLE text_data (category INTEGER, "index" INTEGER, text TEXT);
            CREATE TABLE single_mode_route (
                scenario_id INTEGER, chara_id INTEGER, race_set_id INTEGER
            );
            CREATE TABLE single_mode_route_race (
                id INTEGER, race_set_id INTEGER, target_type INTEGER,
                race_type INTEGER, condition_type INTEGER, condition_id INTEGER,
                condition_value_1 INTEGER, turn INTEGER, sort_id INTEGER
            );
            CREATE TABLE single_mode_program (
                id INTEGER, race_instance_id INTEGER
            );
            CREATE TABLE race_instance (
                id INTEGER, race_id INTEGER, date INTEGER
            );
            CREATE TABLE race (
                id INTEGER, grade INTEGER, "group" INTEGER
            );
            INSERT INTO card_data VALUES (100101, 10);
            INSERT INTO text_data VALUES (4, 100101, 'Target Card');
            INSERT INTO text_data VALUES (6, 10, 'Target Uma');
            INSERT INTO text_data VALUES (28, 2001, 'Mandatory Derby');
            INSERT INTO single_mode_route VALUES (0, 10, 77);
            INSERT INTO single_mode_route_race VALUES
                (1, 77, 1, 0, 1, 501, 1, 34, 1),
                (2, 77, 1, 0, 3, 501, 10000, 36, 2);
            INSERT INTO single_mode_program VALUES (501, 2001);
            INSERT INTO race_instance VALUES (2001, 1022, 528);
            INSERT INTO race VALUES (1022, 100, 1);
            """
        )
        connection.commit()
        connection.close()

        resolver = AffinityResolver(path)
        try:
            objectives = resolver.objective_races(10)
            objectives[0]["name"] = "Mutated caller copy"
            cached_objectives = resolver.objective_races(10)
        finally:
            resolver.close()

    assert len(objectives) == 1
    assert cached_objectives[0]["name"] == "Mandatory Derby"
    assert cached_objectives[0]["objective_slot"] == {
        "year": 2,
        "month": 5,
        "half": 2,
    }
    assert cached_objectives[0]["is_g1"] is True
    assert cached_objectives[0]["required_position"] == 1


class G1RacePlanningTests(unittest.TestCase):
    def test_race_permission_mapping(self) -> None:
        test_race_permission_mapping_matches_the_three_career_years()

    def test_calendar_slot_mapping(self) -> None:
        test_calendar_slots_use_early_and_late_half_months()

    def test_pair_diagnostic(self) -> None:
        test_pair_diagnostic_keeps_shared_and_one_sided_races_with_details()

    def test_schedule_collision(self) -> None:
        test_schedule_keeps_only_the_best_g1_when_a_turn_collides()

    def test_schedule_spacing(self) -> None:
        test_schedule_moves_flexible_g1_to_avoid_three_and_four_race_streaks()

    def test_unavoidable_long_streak_warning(self) -> None:
        test_schedule_keeps_four_race_streak_but_marks_every_race_as_risky()

    def test_schedule_one_race_per_turn(self) -> None:
        test_schedule_never_places_two_g1_on_the_same_turn()

    def test_objectives_and_trackblazer(self) -> None:
        test_standard_plan_locks_objectives_and_trackblazer_ignores_them()

    def test_objective_g1_deduplication(self) -> None:
        test_g1_objective_is_merged_without_duplicate_affinity()

    def test_local_remote_provenance(self) -> None:
        test_one_sided_race_keeps_local_or_remote_provenance()

    def test_streak_year_boundary(self) -> None:
        test_streaks_do_not_cross_a_career_year_boundary()

    def test_master_schedule_enrichment(self) -> None:
        test_master_resolver_enriches_g1_with_calendar_slots()

    def test_fixed_objective_resolution(self) -> None:
        test_affinity_resolver_reads_only_fixed_race_objectives()

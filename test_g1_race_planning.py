import sqlite3
import tempfile
import unittest
from pathlib import Path

from g1_race_planning import (
    build_pair_g1_diagnostic,
    calendar_slots,
    optimize_race_schedule,
    years_for_race_permissions,
)
from legacy_linker import MasterResolver


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
        finally:
            resolver.close()

    detail = resolved["details"][0]
    assert detail["race_id"] == 1022
    assert detail["date"] == 1028
    assert detail["years"] == [2, 3]
    assert detail["schedule_slots"] == [
        {"year": 2, "month": 10, "half": 2},
        {"year": 3, "month": 10, "half": 2},
    ]


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

    def test_schedule_one_race_per_turn(self) -> None:
        test_schedule_never_places_two_g1_on_the_same_turn()

    def test_master_schedule_enrichment(self) -> None:
        test_master_resolver_enriches_g1_with_calendar_slots()

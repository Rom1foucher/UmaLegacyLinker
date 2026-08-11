from __future__ import annotations

import copy
from typing import Any


RACE_PERMISSION_YEARS: dict[int, tuple[int, ...]] = {
    1: (1,),
    2: (2,),
    3: (2, 3),
    4: (3,),
}

INDEPENDENT_TRAINING_STREAK_PENALTIES: dict[int, float] = {
    3: 0.10,
    4: 0.25,
    5: 0.35,
    6: 0.50,
}


def distance_type_for_meters(distance: Any) -> str | None:
    try:
        meters = int(distance)
    except (TypeError, ValueError):
        return None
    if meters <= 0:
        return None
    if meters <= 1400:
        return "sprint"
    if meters <= 1800:
        return "mile"
    if meters <= 2400:
        return "medium"
    return "long"


def surface_for_ground(ground: Any) -> str | None:
    try:
        value = int(ground)
    except (TypeError, ValueError):
        return None
    return {1: "turf", 2: "dirt"}.get(value)


def independent_training_win_probability(
    distance_rank: Any,
    surface_rank: Any,
) -> float | None:
    """Return the Independent Training win table value for two aptitudes.

    The source table treats A and S identically and deliberately reaches 110%
    for A/A.  Keeping that headroom matters because race-streak penalties are
    subtracted afterwards.
    """

    try:
        distance = min(7, max(1, int(distance_rank)))
        surface = min(7, max(1, int(surface_rank)))
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.10, (distance + surface - 3) * 0.10))


def independent_training_streak_penalty(consecutive_race_index: Any) -> float:
    try:
        count = max(1, int(consecutive_race_index))
    except (TypeError, ValueError):
        count = 1
    if count >= 6:
        return INDEPENDENT_TRAINING_STREAK_PENALTIES[6]
    return INDEPENDENT_TRAINING_STREAK_PENALTIES.get(count, 0.0)


def _race_win_probability(
    race: dict[str, Any],
    training_aptitudes: dict[str, Any] | None,
) -> float | None:
    if not isinstance(training_aptitudes, dict):
        return None
    distance = str(race.get("distance_type") or "").strip().lower()
    surface = str(race.get("surface") or "").strip().lower()
    if not distance or not surface:
        return None
    distance_payload = (training_aptitudes.get("distance") or {}).get(distance)
    surface_payload = (training_aptitudes.get("surface") or {}).get(surface)

    def rank(value: Any) -> Any:
        if isinstance(value, dict):
            return value.get("initial_rank", value.get("rank"))
        return value

    return independent_training_win_probability(
        rank(distance_payload),
        rank(surface_payload),
    )


def apply_independent_training_cutoff(
    races: list[dict[str, Any]],
    *,
    training_aptitudes: dict[str, Any] | None,
    win_probability_cutoff: float | None,
) -> None:
    """Annotate races for binary Independent Training G1 eligibility.

    Missing course metadata keeps the legacy behaviour instead of silently
    deleting old/imported G1 records that cannot yet be resolved through MDB.
    """

    cutoff = (
        None
        if win_probability_cutoff is None
        else max(0.0, min(1.10, float(win_probability_cutoff)))
    )
    for race in races:
        base_probability = _race_win_probability(race, training_aptitudes)
        race["independent_training_base_win_probability"] = base_probability
        race["independent_training_win_probability_cutoff"] = cutoff
        race["independent_training_probability_known"] = base_probability is not None
        base_passed = (
            None
            if base_probability is None or cutoff is None
            else base_probability + 1e-12 >= cutoff
        )
        race["independent_training_base_cutoff_passed"] = base_passed
        if base_passed is not None:
            race["effective_affinity_bonus"] = (
                int(race.get("affinity_bonus") or 0) if base_passed else 0
            )


def _effective_race_value(
    race: dict[str, Any],
    consecutive_race_index: int,
) -> tuple[int, float | None, float, bool]:
    bonus = max(0, int(race.get("affinity_bonus") or 0))
    base = race.get("independent_training_base_win_probability")
    cutoff = race.get("independent_training_win_probability_cutoff")
    penalty = independent_training_streak_penalty(consecutive_race_index)
    if base is None or cutoff is None:
        return bonus, None, penalty, True
    effective = max(0.0, float(base) - penalty)
    eligible = effective + 1e-12 >= float(cutoff)
    return bonus if eligible else 0, effective, penalty, eligible


def years_for_race_permissions(values: Any) -> list[int]:
    """Translate MDB ``race_permission`` values into career years.

    The game uses 1 for Junior, 2 for Classic, 3 for Classic + Senior and 4
    for Senior. Other values (notably the URA finale) do not describe a normal
    G1 calendar slot and are intentionally ignored.
    """

    years: set[int] = set()
    for raw in values or []:
        try:
            permission = int(raw)
        except (TypeError, ValueError):
            continue
        years.update(RACE_PERMISSION_YEARS.get(permission, ()))
    return sorted(years)


def calendar_slots(
    *,
    race_date: Any,
    race_permissions: Any,
) -> list[dict[str, int]]:
    """Return every in-game calendar cell in which a race can appear."""

    try:
        date_value = int(race_date)
    except (TypeError, ValueError):
        return []
    month = date_value // 100
    day = date_value % 100
    if month < 1 or month > 12 or day < 1 or day > 31:
        return []
    half = 1 if day <= 15 else 2
    return [
        {"year": year, "month": month, "half": half}
        for year in years_for_race_permissions(race_permissions)
    ]


def _member_g1_payload(member: dict[str, Any] | None) -> tuple[set[str], dict[str, dict[str, Any]]]:
    wins = (member or {}).get("g1_wins") or {}
    if not isinstance(wins, dict):
        return set(), {}
    names = {str(name) for name in wins.get("names") or [] if str(name).strip()}
    details: dict[str, dict[str, Any]] = {}
    for raw in wins.get("details") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        names.add(name)
        detail = dict(raw)
        detail["name"] = name
        details.setdefault(name, detail)
    return names, details


def _merge_race_details(
    name: str,
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {"name": name}
    for detail in (left or {}, right or {}):
        for key, value in detail.items():
            if key == "schedule_slots":
                continue
            if value not in (None, "", [], {}):
                merged.setdefault(key, value)

    slots: set[tuple[int, int, int]] = set()
    for detail in (left or {}, right or {}):
        for slot in detail.get("schedule_slots") or []:
            if not isinstance(slot, dict):
                continue
            try:
                key = (
                    int(slot.get("year")),
                    int(slot.get("month")),
                    int(slot.get("half")),
                )
            except (TypeError, ValueError):
                continue
            if key[0] in (1, 2, 3) and 1 <= key[1] <= 12 and key[2] in (1, 2):
                slots.add(key)
    if not slots:
        slots.update(
            (
                int(slot["year"]),
                int(slot["month"]),
                int(slot["half"]),
            )
            for slot in calendar_slots(
                race_date=merged.get("date"),
                race_permissions=merged.get("race_permissions"),
            )
        )
    merged["schedule_slots"] = [
        {"year": year, "month": month, "half": half}
        for year, month, half in sorted(slots)
    ]
    return merged


def _race_sort_key(race: dict[str, Any]) -> tuple[int, int, int, str]:
    slots = race.get("schedule_slots") or []
    if slots:
        first = min(
            slots,
            key=lambda slot: (
                int(slot.get("year") or 99),
                int(slot.get("month") or 99),
                int(slot.get("half") or 99),
            ),
        )
        return (
            int(first.get("year") or 99),
            int(first.get("month") or 99),
            int(first.get("half") or 99),
            str(race.get("name") or "").casefold(),
        )
    return (99, 99, 99, str(race.get("name") or "").casefold())


def _valid_slot_keys(race: dict[str, Any]) -> tuple[tuple[int, int, int], ...]:
    slots: set[tuple[int, int, int]] = set()
    for raw in race.get("schedule_slots") or []:
        if not isinstance(raw, dict):
            continue
        try:
            key = (
                int(raw.get("year")),
                int(raw.get("month")),
                int(raw.get("half")),
            )
        except (TypeError, ValueError):
            continue
        if key[0] in (1, 2, 3) and 1 <= key[1] <= 12 and key[2] in (1, 2):
            slots.add(key)
    return tuple(sorted(slots))


def _phase_index(month: int, half: int) -> int:
    return (month - 1) * 2 + (half - 1)


def _phase_options(
    race_indexes: list[int],
    races: list[dict[str, Any]],
    slot_keys: dict[int, tuple[tuple[int, int, int], ...]],
) -> list[dict[str, Any]]:
    """Enumerate the useful one-race-per-year choices for one calendar turn.

    The same G1 can generally be run in Classic or Senior year. Every option
    therefore assigns each selected race to at most one year and keeps at most
    one race in each of the three year cells for this turn.
    """

    ordered = sorted(
        race_indexes,
        key=lambda index: (
            -int(races[index].get("affinity_bonus") or 0),
            str(races[index].get("name") or "").casefold(),
            index,
        ),
    )
    options: list[dict[str, Any]] = []
    empty_profile = (0, 0, 0, 0, 0, 0)
    race_value_profiles = {
        index: tuple(
            _effective_race_value(races[index], run_position)[0]
            for run_position in range(1, 7)
        )
        for index in ordered
    }

    def visit(
        position: int,
        used_years: set[int],
        assignments: list[tuple[int, int]],
    ) -> None:
        if position >= len(ordered):
            mask = sum(1 << (year - 1) for year in used_years)
            options.append({
                "mask": mask,
                "assignments": tuple(sorted(assignments)),
                "race_count": len(assignments),
                "affinity_race_count": sum(
                    int(races[index].get("affinity_bonus") or 0) > 0
                    for _year, index in assignments
                ),
            })
            return

        race_index = ordered[position]
        available_years = sorted(
            {year for year, _month, _half in slot_keys[race_index]}
        )
        mandatory = bool(races[race_index].get("mandatory_objective"))
        if not mandatory:
            visit(position + 1, used_years, assignments)
        for year in available_years:
            if year in used_years:
                continue
            used_years.add(year)
            assignments.append((year, race_index))
            visit(
                position + 1,
                used_years,
                assignments,
            )
            assignments.pop()
            used_years.remove(year)

    visit(0, set(), [])
    # Many assignments differ only by the concrete race chosen for a year but
    # produce exactly the same value for every possible incoming streak. Keep
    # one representative per value profile so the 24-phase DP stays fast while
    # preserving the binary cutoff semantics.
    compact: dict[tuple[Any, ...], dict[str, Any]] = {}
    for option in options:
        assignments_by_year = {
            year: race_index for year, race_index in option["assignments"]
        }
        value_profile = tuple(
            race_value_profiles.get(race_index, empty_profile)
            for race_index in (
                assignments_by_year.get(1),
                assignments_by_year.get(2),
                assignments_by_year.get(3),
            )
        )
        key = (
            int(option["mask"]),
            int(option["affinity_race_count"]),
            int(option["race_count"]),
            value_profile,
        )
        compact.setdefault(key, option)
    return sorted(
        compact.values(),
        key=lambda option: (
            int(option["mask"]),
            tuple(option["assignments"]),
        ),
    )


def _streak_summary(planned_slots: set[tuple[int, int, int]]) -> dict[str, int]:
    lengths: list[int] = []
    for year in (1, 2, 3):
        current = 0
        for month in range(1, 13):
            for half in (1, 2):
                if (year, month, half) in planned_slots:
                    current += 1
                elif current:
                    lengths.append(current)
                    current = 0
        if current:
            lengths.append(current)
    return {
        "max_consecutive": max(lengths, default=0),
        "runs_of_2": sum(length == 2 for length in lengths),
        "runs_of_3": sum(length == 3 for length in lengths),
        "runs_of_4_plus": sum(length >= 4 for length in lengths),
    }


def _streak_lengths(
    planned_slots: set[tuple[int, int, int]],
) -> dict[tuple[int, int, int], int]:
    """Map every planned turn to the length of its consecutive race run."""

    result: dict[tuple[int, int, int], int] = {}
    for year in (1, 2, 3):
        current: list[tuple[int, int, int]] = []
        for month in range(1, 13):
            for half in (1, 2):
                slot = (year, month, half)
                if slot in planned_slots:
                    current.append(slot)
                    continue
                if current:
                    length = len(current)
                    result.update({item: length for item in current})
                    current = []
        if current:
            length = len(current)
            result.update({item: length for item in current})
    return result


def _streak_positions(
    planned_slots: set[tuple[int, int, int]],
) -> dict[tuple[int, int, int], int]:
    """Map each race turn to its ordinal position inside the current streak."""

    result: dict[tuple[int, int, int], int] = {}
    for year in (1, 2, 3):
        current = 0
        for month in range(1, 13):
            for half in (1, 2):
                slot = (year, month, half)
                if slot in planned_slots:
                    current += 1
                    result[slot] = current
                else:
                    current = 0
    return result


def optimize_race_schedule(
    races: list[dict[str, Any]],
    *,
    max_affinity_races: int | None = None,
) -> dict[str, Any]:
    """Build an optimal, executable three-year G1 schedule.

    The objective is lexicographic: maximise obtainable affinity, minimise
    turns belonging to 4+ race streaks, then 3+ and 2+ streaks, and finally
    minimise the number of races when the affinity and spacing are identical.
    """

    slot_keys = {
        index: _valid_slot_keys(race)
        for index, race in enumerate(races)
    }
    phases: dict[int, list[int]] = {phase: [] for phase in range(24)}
    incompatible_phase_indexes: set[int] = set()
    for index, keys in slot_keys.items():
        phase_values = {
            _phase_index(month, half)
            for _year, month, half in keys
        }
        if not phase_values:
            continue
        if len(phase_values) != 1:
            incompatible_phase_indexes.add(index)
            continue
        phases[next(iter(phase_values))].append(index)

    # state -> (bonus, 4+ turns, 3+ turns, 2+ turns, race count, choices)
    budget = (
        None
        if max_affinity_races is None
        else max(0, int(max_affinity_races))
    )
    states: dict[
        tuple[int, int, int, int],
        tuple[int, int, int, int, int, tuple[tuple[tuple[int, int], ...], ...]],
    ] = {(0, 0, 0, 0): (0, 0, 0, 0, 0, ())}
    for phase in range(24):
        options = _phase_options(phases[phase], races, slot_keys)
        next_states: dict[
            tuple[int, int, int, int],
            tuple[int, int, int, int, int, tuple[tuple[tuple[int, int], ...], ...]],
        ] = {}
        for state, current in states.items():
            runs = state[:3]
            affinity_race_count = state[3]
            for option in options:
                new_affinity_race_count = affinity_race_count + int(
                    option["affinity_race_count"]
                )
                if budget is not None and new_affinity_race_count > budget:
                    continue
                new_runs: list[int] = []
                added_four = 0
                added_three = 0
                added_two = 0
                mask = int(option["mask"])
                for year_index, run in enumerate(runs):
                    if mask & (1 << year_index):
                        new_run = run + 1
                        added_four += int(new_run >= 4)
                        added_three += int(new_run >= 3)
                        added_two += int(new_run >= 2)
                    else:
                        new_run = 0
                    new_runs.append(new_run)
                effective_bonus = sum(
                    _effective_race_value(races[race_index], new_runs[year - 1])[0]
                    for year, race_index in option["assignments"]
                )
                candidate = (
                    current[0] + effective_bonus,
                    current[1] + added_four,
                    current[2] + added_three,
                    current[3] + added_two,
                    current[4] + int(option["race_count"]),
                    current[5] + (tuple(option["assignments"]),),
                )
                state_key = (*new_runs, new_affinity_race_count)
                previous = next_states.get(state_key)
                candidate_score = (
                    candidate[0],
                    -candidate[1],
                    -candidate[2],
                    -candidate[3],
                    -candidate[4],
                )
                previous_score = (
                    (
                        previous[0],
                        -previous[1],
                        -previous[2],
                        -previous[3],
                        -previous[4],
                    )
                    if previous is not None
                    else None
                )
                if previous_score is None or candidate_score > previous_score:
                    next_states[state_key] = candidate
        states = next_states

    best = max(
        states.values(),
        key=lambda value: (
            value[0],
            -value[1],
            -value[2],
            -value[3],
            -value[4],
        ),
    )
    selected: dict[int, tuple[int, int, int]] = {}
    for phase, assignments in enumerate(best[5]):
        month = phase // 2 + 1
        half = phase % 2 + 1
        for year, race_index in assignments:
            selected[race_index] = (year, month, half)

    scheduled_races: list[dict[str, Any]] = []
    excluded_races: list[dict[str, Any]] = []
    missing_calendar_races: list[dict[str, Any]] = []
    planned_slots: set[tuple[int, int, int]] = set()
    objective_slots = {
        slot
        for index, slot in selected.items()
        if bool(races[index].get("mandatory_objective"))
    }
    for index, race in enumerate(races):
        slot = selected.get(index)
        if slot is not None:
            race["planned_slot"] = {
                "year": slot[0],
                "month": slot[1],
                "half": slot[2],
            }
            race["planning_status"] = "scheduled"
            planned_slots.add(slot)
            scheduled_races.append(race)
        elif slot_keys[index]:
            race["planned_slot"] = None
            race["planning_status"] = (
                "unsupported_calendar"
                if index in incompatible_phase_indexes
                else "objective_conflict"
                if any(key in objective_slots for key in slot_keys[index])
                else "below_win_cutoff"
                if race.get("independent_training_base_cutoff_passed") is False
                else "calendar_conflict"
            )
            excluded_races.append(race)
        else:
            race["planned_slot"] = None
            race["planning_status"] = "missing_calendar"
            missing_calendar_races.append(race)

    streak_lengths = _streak_lengths(planned_slots)
    streak_positions = _streak_positions(planned_slots)
    for race in scheduled_races:
        planned = race.get("planned_slot") or {}
        slot = (
            int(planned.get("year") or 0),
            int(planned.get("month") or 0),
            int(planned.get("half") or 0),
        )
        length = streak_lengths.get(slot, 1)
        position = streak_positions.get(slot, 1)
        effective_bonus, effective_probability, penalty, eligible = _effective_race_value(
            race, position
        )
        race["consecutive_race_count"] = length
        race["consecutive_race_index"] = position
        race["long_streak_warning"] = length >= 4
        race["independent_training_streak_penalty"] = penalty
        race["independent_training_effective_win_probability"] = effective_probability
        race["independent_training_cutoff_passed"] = eligible
        race["effective_affinity_bonus"] = effective_bonus

    optimal_bonus = sum(
        int(race.get("effective_affinity_bonus") or 0)
        for race in scheduled_races
    )
    theoretical_bonus = sum(
        int(race.get("affinity_bonus") or 0)
        for race in races
    )
    scheduled_affinity_races = [
        race
        for race in scheduled_races
        if int(race.get("effective_affinity_bonus") or 0) > 0
    ]
    scheduled_objectives = [
        race
        for race in scheduled_races
        if bool(race.get("mandatory_objective"))
    ]
    return {
        "scheduled_races": scheduled_races,
        "excluded_races": excluded_races,
        "missing_calendar_races": missing_calendar_races,
        "optimal_bonus": optimal_bonus,
        "lost_bonus": max(0, theoretical_bonus - optimal_bonus),
        "optimal_race_count": len(scheduled_races),
        "optimal_affinity_race_count": len(scheduled_affinity_races),
        "max_affinity_races": budget,
        "scheduled_objective_race_count": len(scheduled_objectives),
        "excluded_race_count": len(excluded_races),
        "missing_calendar_race_count": len(missing_calendar_races),
        "streaks": _streak_summary(planned_slots),
    }


def _race_identity(race: dict[str, Any]) -> tuple[str, object]:
    for key in ("race_id", "race_instance_id"):
        value = race.get(key)
        if value not in (None, "", 0, "0"):
            try:
                return key, int(value)
            except (TypeError, ValueError):
                return key, str(value)
    return "name", str(race.get("name") or "").strip().casefold()


def _objective_slot(race: dict[str, Any]) -> dict[str, int] | None:
    raw = race.get("objective_slot")
    if not isinstance(raw, dict):
        slots = race.get("schedule_slots") or []
        raw = slots[0] if len(slots) == 1 and isinstance(slots[0], dict) else None
    if not isinstance(raw, dict):
        return None
    try:
        slot = {
            "year": int(raw.get("year")),
            "month": int(raw.get("month")),
            "half": int(raw.get("half")),
        }
    except (TypeError, ValueError):
        return None
    if slot["year"] not in (1, 2, 3):
        return None
    if not 1 <= slot["month"] <= 12 or slot["half"] not in (1, 2):
        return None
    return slot


def _schedule_variant(
    affinity_races: list[dict[str, Any]],
    objective_races: list[dict[str, Any]],
    *,
    include_objectives: bool,
    max_affinity_races: int | None = None,
) -> dict[str, Any]:
    races = copy.deepcopy(affinity_races)
    objectives = copy.deepcopy(objective_races) if include_objectives else []
    unmatched_by_identity: dict[tuple[str, object], list[int]] = {}
    for index, race in enumerate(races):
        unmatched_by_identity.setdefault(_race_identity(race), []).append(index)

    for objective in objectives:
        slot = _objective_slot(objective)
        if slot is None:
            continue
        identity = _race_identity(objective)
        matching_indexes = unmatched_by_identity.get(identity) or []
        matching_index = next(
            (
                index
                for index in matching_indexes
                if not bool(races[index].get("mandatory_objective"))
            ),
            None,
        )
        objective_detail = {
            key: copy.deepcopy(value)
            for key, value in objective.items()
            if key not in {"planned_slot", "planning_status"}
        }
        if matching_index is not None:
            race = races[matching_index]
            race["mandatory_objective"] = True
            race["objective"] = True
            race["objective_only"] = False
            race["objective_slot"] = dict(slot)
            race["objective_details"] = [objective_detail]
            # Winning the objective already realizes this race-affinity link.
            # Do not schedule the same G1 again in another career year.
            race["schedule_slots"] = [dict(slot)]
            continue

        races.append(
            {
                **objective_detail,
                "mandatory_objective": True,
                "objective": True,
                "objective_only": True,
                "objective_slot": dict(slot),
                "objective_details": [objective_detail],
                "schedule_slots": [dict(slot)],
                "sources": [],
                "source_sides": [],
                "source_origins": [],
                "owner_count": 0,
                "shared": False,
                "affinity_bonus": 0,
            }
        )

    schedule = optimize_race_schedule(
        races,
        max_affinity_races=max_affinity_races,
    )
    return {
        "mode": "standard" if include_objectives else "trackblazer",
        "considers_objectives": include_objectives,
        "races": races,
        "objective_races": objectives,
        "objective_race_count": len(objectives),
        **schedule,
    }


def build_pair_g1_diagnostic(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    left_label: str,
    right_label: str,
    left_origin: str | None = None,
    right_origin: str | None = None,
    target: dict[str, Any] | None = None,
    objective_races: list[dict[str, Any]] | None = None,
    bonus_per_link: int = 3,
    training_aptitudes: dict[str, Any] | None = None,
    win_probability_cutoff: float | None = None,
    max_affinity_races: int | None = None,
) -> dict[str, Any]:
    """Describe the optimal G1 plan for a trainee built from two legacies.

    A race already won by both selected legacies creates two new race-affinity
    links when the trainee also wins it, hence ``+6`` with the default modern
    ``+3`` per link. A one-sided race creates one link and is worth ``+3``.
    """

    left_names, left_details = _member_g1_payload(left)
    right_names, right_details = _member_g1_payload(right)
    common_names = sorted(left_names & right_names)
    left_only_names = sorted(left_names - right_names)
    right_only_names = sorted(right_names - left_names)
    resolved_bonus = max(0, int(bonus_per_link))

    resolved_left_origin = str(left_origin or "left")
    resolved_right_origin = str(right_origin or "right")

    def race(
        name: str,
        sources: list[str],
        source_sides: list[str],
        source_origins: list[str],
    ) -> dict[str, Any]:
        detail = _merge_race_details(
            name,
            left_details.get(name),
            right_details.get(name),
        )
        owner_count = len(sources)
        return {
            **detail,
            "sources": sources,
            "source_sides": source_sides,
            "source_origins": source_origins,
            "owner_count": owner_count,
            "shared": owner_count == 2,
            "affinity_bonus": owner_count * resolved_bonus,
        }

    common = [
        race(
            name,
            [left_label, right_label],
            ["left", "right"],
            [resolved_left_origin, resolved_right_origin],
        )
        for name in common_names
    ]
    left_only = [
        race(
            name,
            [left_label],
            ["left"],
            [resolved_left_origin],
        )
        for name in left_only_names
    ]
    right_only = [
        race(
            name,
            [right_label],
            ["right"],
            [resolved_right_origin],
        )
        for name in right_only_names
    ]
    races = sorted(common + left_only + right_only, key=_race_sort_key)
    apply_independent_training_cutoff(
        races,
        training_aptitudes=training_aptitudes,
        win_probability_cutoff=win_probability_cutoff,
    )
    exact_bonus = sum(int(item["affinity_bonus"]) for item in races)
    resolved_objectives = [
        dict(race)
        for race in (objective_races or [])
        if isinstance(race, dict)
    ]
    standard_schedule = _schedule_variant(
        races,
        resolved_objectives,
        include_objectives=True,
        max_affinity_races=max_affinity_races,
    )
    trackblazer_schedule = _schedule_variant(
        races,
        resolved_objectives,
        include_objectives=False,
        max_affinity_races=max_affinity_races,
    )
    scheduled_count = int(standard_schedule["optimal_affinity_race_count"])
    target_identity = {
        key: target.get(key)
        for key in ("card_id", "chara_id", "uma_name", "card_name")
        if isinstance(target, dict) and target.get(key) is not None
    }

    return {
        "model": "new_trainee_race_affinity_plan",
        "left_label": left_label,
        "right_label": right_label,
        "left_origin": resolved_left_origin,
        "right_origin": resolved_right_origin,
        "target": target_identity,
        "bonus_per_link": resolved_bonus,
        "shared_race_bonus": 2 * resolved_bonus,
        "one_side_race_bonus": resolved_bonus,
        "independent_training_aptitudes": copy.deepcopy(training_aptitudes),
        "g1_win_probability_cutoff": win_probability_cutoff,
        "max_affinity_races": max_affinity_races,
        "common_g1_names": common_names,
        "left_only_g1_names": left_only_names,
        "right_only_g1_names": right_only_names,
        "common_g1_count": len(common),
        "left_only_g1_count": len(left_only),
        "right_only_g1_count": len(right_only),
        "common_g1": common,
        "left_only_g1": left_only,
        "right_only_g1": right_only,
        "affinity_races": copy.deepcopy(races),
        "objective_races": resolved_objectives,
        "objective_race_count": len(resolved_objectives),
        "schedule_variants": {
            "standard": standard_schedule,
            "trackblazer": trackblazer_schedule,
        },
        "race_count": len(races),
        "scheduled_race_count": scheduled_count,
        "unscheduled_race_count": len(races) - scheduled_count,
        "exact_bonus_if_all_won": exact_bonus,
        **standard_schedule,
        "formula": (
            "new trainee wins × selected legacy wins: "
            "two matching legacies create two links; one matching legacy creates one link; "
            "a race contributes its full link value only when its Independent Training win "
            "probability after streak penalty reaches the configured cutoff"
        ),
    }


def schedule_export_summary(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Return stable scalar metrics for CSV and compact diagnostic exports."""

    resolved = plan if isinstance(plan, dict) else {}
    variants = resolved.get("schedule_variants") or {}
    standard = (
        variants.get("standard")
        if isinstance(variants, dict) and isinstance(variants.get("standard"), dict)
        else resolved
    )
    trackblazer = (
        variants.get("trackblazer")
        if isinstance(variants, dict)
        and isinstance(variants.get("trackblazer"), dict)
        else {}
    )
    objective_conflicts = sum(
        str(race.get("planning_status") or "") == "objective_conflict"
        for race in standard.get("races") or []
        if isinstance(race, dict)
    )
    races = [race for race in standard.get("races") or [] if isinstance(race, dict)]
    summary: dict[str, Any] = {
        "standard_optimal_bonus": int(standard.get("optimal_bonus") or 0),
        "trackblazer_optimal_bonus": int(
            trackblazer.get("optimal_bonus")
            or standard.get("optimal_bonus")
            or 0
        ),
        "objective_race_count": int(
            standard.get("objective_race_count")
            or resolved.get("objective_race_count")
            or 0
        ),
        "objective_conflict_count": objective_conflicts,
    }
    if resolved.get("g1_win_probability_cutoff") is not None:
        summary.update({
            "g1_win_probability_cutoff": resolved.get("g1_win_probability_cutoff"),
            "known_win_probability_race_count": sum(
                bool(race.get("independent_training_probability_known")) for race in races
            ),
            "below_win_cutoff_race_count": sum(
                race.get("planning_status") == "below_win_cutoff" for race in races
            ),
        })
    return summary

from __future__ import annotations

from typing import Any


RACE_PERMISSION_YEARS: dict[int, tuple[int, ...]] = {
    1: (1,),
    2: (2,),
    3: (2, 3),
    4: (3,),
}


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
    best_by_mask: dict[int, dict[str, Any]] = {}

    def visit(
        position: int,
        used_years: set[int],
        assignments: list[tuple[int, int]],
        bonus: int,
    ) -> None:
        if position >= len(ordered):
            mask = sum(1 << (year - 1) for year in used_years)
            candidate = {
                "mask": mask,
                "assignments": tuple(sorted(assignments)),
                "bonus": bonus,
                "race_count": len(assignments),
            }
            previous = best_by_mask.get(mask)
            candidate_score = (bonus, -len(assignments))
            previous_score = (
                (int(previous["bonus"]), -int(previous["race_count"]))
                if previous is not None
                else None
            )
            if previous_score is None or candidate_score > previous_score:
                best_by_mask[mask] = candidate
            return

        race_index = ordered[position]
        visit(position + 1, used_years, assignments, bonus)
        available_years = sorted(
            {year for year, _month, _half in slot_keys[race_index]}
        )
        race_bonus = int(races[race_index].get("affinity_bonus") or 0)
        for year in available_years:
            if year in used_years:
                continue
            used_years.add(year)
            assignments.append((year, race_index))
            visit(
                position + 1,
                used_years,
                assignments,
                bonus + race_bonus,
            )
            assignments.pop()
            used_years.remove(year)

    visit(0, set(), [], 0)
    return sorted(
        best_by_mask.values(),
        key=lambda option: (
            int(option["mask"]),
            tuple(option["assignments"]),
        ),
    )


def _streak_summary(planned_slots: set[tuple[int, int, int]]) -> dict[str, int]:
    lengths: list[int] = []
    current = 0
    for year in (1, 2, 3):
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


def optimize_race_schedule(races: list[dict[str, Any]]) -> dict[str, Any]:
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
    states: dict[
        tuple[int, int, int],
        tuple[int, int, int, int, int, tuple[tuple[tuple[int, int], ...], ...]],
    ] = {(0, 0, 0): (0, 0, 0, 0, 0, ())}
    for phase in range(24):
        options = _phase_options(phases[phase], races, slot_keys)
        next_states: dict[
            tuple[int, int, int],
            tuple[int, int, int, int, int, tuple[tuple[tuple[int, int], ...], ...]],
        ] = {}
        for runs, current in states.items():
            for option in options:
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
                candidate = (
                    current[0] + int(option["bonus"]),
                    current[1] + added_four,
                    current[2] + added_three,
                    current[3] + added_two,
                    current[4] + int(option["race_count"]),
                    current[5] + (tuple(option["assignments"]),),
                )
                state_key = tuple(new_runs)
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
                else "calendar_conflict"
            )
            excluded_races.append(race)
        else:
            race["planned_slot"] = None
            race["planning_status"] = "missing_calendar"
            missing_calendar_races.append(race)

    optimal_bonus = sum(
        int(race.get("affinity_bonus") or 0)
        for race in scheduled_races
    )
    theoretical_bonus = sum(
        int(race.get("affinity_bonus") or 0)
        for race in races
    )
    return {
        "scheduled_races": scheduled_races,
        "excluded_races": excluded_races,
        "missing_calendar_races": missing_calendar_races,
        "optimal_bonus": optimal_bonus,
        "lost_bonus": max(0, theoretical_bonus - optimal_bonus),
        "optimal_race_count": len(scheduled_races),
        "excluded_race_count": len(excluded_races),
        "missing_calendar_race_count": len(missing_calendar_races),
        "streaks": _streak_summary(planned_slots),
    }


def build_pair_g1_diagnostic(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    left_label: str,
    right_label: str,
    bonus_per_link: int = 3,
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

    def race(name: str, sources: list[str]) -> dict[str, Any]:
        detail = _merge_race_details(
            name,
            left_details.get(name),
            right_details.get(name),
        )
        owner_count = len(sources)
        return {
            **detail,
            "sources": sources,
            "owner_count": owner_count,
            "shared": owner_count == 2,
            "affinity_bonus": owner_count * resolved_bonus,
        }

    common = [race(name, [left_label, right_label]) for name in common_names]
    left_only = [race(name, [left_label]) for name in left_only_names]
    right_only = [race(name, [right_label]) for name in right_only_names]
    races = sorted(common + left_only + right_only, key=_race_sort_key)
    exact_bonus = sum(int(item["affinity_bonus"]) for item in races)
    schedule = optimize_race_schedule(races)
    scheduled_count = int(schedule["optimal_race_count"])

    return {
        "model": "new_trainee_race_affinity_plan",
        "left_label": left_label,
        "right_label": right_label,
        "bonus_per_link": resolved_bonus,
        "shared_race_bonus": 2 * resolved_bonus,
        "one_side_race_bonus": resolved_bonus,
        "common_g1_names": common_names,
        "left_only_g1_names": left_only_names,
        "right_only_g1_names": right_only_names,
        "common_g1_count": len(common),
        "left_only_g1_count": len(left_only),
        "right_only_g1_count": len(right_only),
        "common_g1": common,
        "left_only_g1": left_only,
        "right_only_g1": right_only,
        "races": races,
        "race_count": len(races),
        "scheduled_race_count": scheduled_count,
        "unscheduled_race_count": len(races) - scheduled_count,
        "exact_bonus_if_all_won": exact_bonus,
        **schedule,
        "formula": (
            "new trainee wins × selected legacy wins: "
            "two matching legacies create two links; one matching legacy creates one link"
        ),
    }

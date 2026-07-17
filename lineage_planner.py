from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from legacy_linker import MasterResolver, normalize_json_root


LINEAGE_PLANNER_URL = "https://uma.moe/tools/lineage-planner"

FACTOR_TYPE_CODES = {
    "blue_stat": 0,
    "red_aptitude": 1,
    "white_race": 2,
    "white_skill": 3,
    "scenario": 4,
    "unique": 5,
}

POSITION_ORDER = (
    "target",
    "p1",
    "p2",
    "p1-1",
    "p1-2",
    "p2-1",
    "p2-2",
    "p1-1-1",
    "p1-1-2",
    "p1-2-1",
    "p1-2-2",
    "p2-1-1",
    "p2-1-2",
    "p2-2-1",
    "p2-2-2",
)

RAW_LINEAGE_POSITIONS = {
    10: "{parent}-1",
    20: "{parent}-2",
    11: "{parent}-1-1",
    12: "{parent}-1-2",
    21: "{parent}-2-1",
    22: "{parent}-2-2",
}


class LineagePlannerError(RuntimeError):
    pass


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def _utc_timestamp(value: datetime | None = None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _planner_factor(factor: dict[str, Any]) -> dict[str, Any] | None:
    type_code = FACTOR_TYPE_CODES.get(str(factor.get("type") or ""))
    if type_code is None:
        return None

    raw_factor_id = _integer(factor.get("factor_id"))
    factor_id = raw_factor_id // 10 if raw_factor_id is not None else None
    if factor_id is None:
        factor_id = _integer(factor.get("factor_group_id"))
    stars = _integer(factor.get("stars"))
    if stars is None and raw_factor_id is not None:
        stars = raw_factor_id % 10
    if factor_id is None or factor_id <= 0 or stars is None or stars <= 0:
        return None

    return {
        "factorId": str(factor_id),
        "level": stars,
        "name": str(factor.get("name") or factor_id),
        "type": type_code,
    }


def _planner_factors(member: dict[str, Any]) -> list[dict[str, Any]]:
    factors = (member.get("factors") or {}).get("all") or []
    result = [
        converted
        for factor in factors
        if isinstance(factor, dict)
        for converted in [_planner_factor(factor)]
        if converted is not None
    ]

    def sort_key(factor: dict[str, Any]) -> tuple[int, int, int | str]:
        factor_id = str(factor["factorId"])
        numeric_id: int | str = int(factor_id) if factor_id.isdigit() else factor_id
        return (-int(factor["level"]), int(factor["type"]), numeric_id)

    return sorted(result, key=sort_key)


def _planner_entry(
    position: str,
    member: dict[str, Any],
    *,
    veteran: dict[str, Any] | None = None,
    succession: dict[str, Any] | None = None,
) -> dict[str, Any]:
    card_id = _integer(member.get("card_id"))
    if card_id is None or card_id <= 0:
        raise LineagePlannerError(
            f"Cannot export {position}: the costume variant ID is missing."
        )
    return {
        "position": position,
        "characterId": card_id,
        "sparks": _planner_factors(member),
        "veteran": veteran,
        "succession": succession,
        "manualWinSaddleIds": [],
    }


def _resolve_raw_member(
    resolver: MasterResolver,
    raw_member: dict[str, Any],
) -> dict[str, Any]:
    card_id = _integer(raw_member.get("card_id"))
    if card_id is None:
        raise LineagePlannerError("A lineage member has no costume variant ID.")
    return {
        **resolver.resolve_card(card_id),
        "factors": resolver.resolve_factors(
            raw_member.get("factor_info_array"), set()
        ),
    }


def _raw_veteran_index(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    if not path.is_file():
        raise LineagePlannerError(f"Veteran export not found: {path}")
    payload = _read_json(path)
    return {
        trained_id: veteran
        for veteran in normalize_json_root(payload)
        if isinstance(veteran, dict)
        for trained_id in [_integer(veteran.get("trained_chara_id"))]
        if trained_id is not None
    }


def _raw_veteran_for(
    member: dict[str, Any],
    raw_veterans: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    trained_id = _integer(member.get("trained_chara_id"))
    return raw_veterans.get(trained_id) if trained_id is not None else None


def _add_normalized_descendants(
    entries: dict[str, dict[str, Any]],
    member: dict[str, Any],
    position: str,
    *,
    depth: int = 0,
) -> None:
    if depth >= 2:
        return
    lineage = member.get("when_used_as_parent") or {}
    for index, key in ((1, "grandparent_1"), (2, "grandparent_2")):
        descendant = lineage.get(key)
        if not isinstance(descendant, dict):
            continue
        child_position = f"{position}-{index}"
        entries[child_position] = _planner_entry(child_position, descendant)
        _add_normalized_descendants(
            entries, descendant, child_position, depth=depth + 1
        )


def _add_parent_branch(
    entries: dict[str, dict[str, Any]],
    position: str,
    member: dict[str, Any],
    *,
    raw_veterans: dict[int, dict[str, Any]],
    resolver: MasterResolver | None,
) -> None:
    raw_veteran = _raw_veteran_for(member, raw_veterans)
    resolved_member = member
    if raw_veteran is not None:
        if resolver is None:
            raise LineagePlannerError(
                "master.mdb is required to resolve the local veteran lineage."
            )
        resolved_member = _resolve_raw_member(resolver, raw_veteran)
    elif not (member.get("factors") or {}).get("all"):
        raise LineagePlannerError(
            f"Cannot resolve the selected local veteran for {position} in data.json."
        )

    entries[position] = _planner_entry(
        position,
        resolved_member,
        veteran=raw_veteran,
    )

    if raw_veteran is None:
        _add_normalized_descendants(entries, member, position)
        return

    for snapshot in raw_veteran.get("succession_chara_array", []) or []:
        if not isinstance(snapshot, dict):
            continue
        raw_position = _integer(snapshot.get("position_id"))
        template = RAW_LINEAGE_POSITIONS.get(raw_position or -1)
        if template is None:
            continue
        child_position = template.format(parent=position)
        resolved_snapshot = _resolve_raw_member(resolver, snapshot)
        entries[child_position] = _planner_entry(
            child_position,
            resolved_snapshot,
            succession=snapshot,
        )


def build_lineage_planner_export(
    ace: dict[str, Any] | int,
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    *,
    master_path: str | Path | None = None,
    veterans_json_path: str | Path | None = None,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an uma.moe Lineage Planner v1 import from a ranked parent pair."""
    ace_card_id = _integer(ace if isinstance(ace, int) else ace.get("card_id"))
    if ace_card_id is None or ace_card_id <= 0:
        raise LineagePlannerError("The target Ace costume variant is missing.")

    raw_path = (
        Path(veterans_json_path).expanduser().resolve()
        if veterans_json_path is not None
        else None
    )
    raw_veterans = _raw_veteran_index(raw_path)
    needs_resolver = bool(
        _raw_veteran_for(parent_1, raw_veterans)
        or _raw_veteran_for(parent_2, raw_veterans)
    )
    resolver: MasterResolver | None = None
    if needs_resolver:
        if master_path is None:
            raise LineagePlannerError(
                "master.mdb is required to export local veteran lineages."
            )
        master = Path(master_path).expanduser().resolve()
        if not master.is_file():
            raise LineagePlannerError(f"master.mdb not found: {master}")
        resolver = MasterResolver(master)

    entries: dict[str, dict[str, Any]] = {
        "target": {
            "position": "target",
            "characterId": ace_card_id,
            "sparks": [],
            "veteran": None,
            "succession": None,
            "manualWinSaddleIds": [],
        }
    }
    try:
        _add_parent_branch(
            entries,
            "p1",
            parent_1,
            raw_veterans=raw_veterans,
            resolver=resolver,
        )
        _add_parent_branch(
            entries,
            "p2",
            parent_2,
            raw_veterans=raw_veterans,
            resolver=resolver,
        )
    finally:
        if resolver is not None:
            resolver.close()

    return {
        "version": 1,
        "type": "lineage-planner",
        "exportedAt": _utc_timestamp(exported_at),
        "payload": [entries[position] for position in POSITION_ORDER if position in entries],
    }


def write_lineage_planner_export(
    path: str | Path,
    ace: dict[str, Any] | int,
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    *,
    master_path: str | Path | None = None,
    veterans_json_path: str | Path | None = None,
) -> Path:
    destination = Path(path).expanduser().resolve()
    payload = build_lineage_planner_export(
        ace,
        parent_1,
        parent_2,
        master_path=master_path,
        veterans_json_path=veterans_json_path,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination

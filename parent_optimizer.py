from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


SURFACES = ("turf", "dirt")
DISTANCES = ("sprint", "mile", "medium", "long")
STYLES = ("front_runner", "pace_chaser", "late_surger", "end_closer")

SURFACE_FACTOR_NAMES = {"turf": "Turf", "dirt": "Dirt"}
DISTANCE_FACTOR_NAMES = {
    "sprint": "Sprint",
    "mile": "Mile",
    "medium": "Medium",
    "long": "Long",
}
STYLE_FACTOR_NAMES = {
    "front_runner": "Front Runner",
    "pace_chaser": "Pace Chaser",
    "late_surger": "Late Surger",
    "end_closer": "End Closer",
}

APTITUDE_COLUMNS = {
    "surface": {
        "turf": "proper_ground_turf",
        "dirt": "proper_ground_dirt",
    },
    "distance": {
        "sprint": "proper_distance_short",
        "mile": "proper_distance_mile",
        "medium": "proper_distance_middle",
        "long": "proper_distance_long",
    },
    "style": {
        "front_runner": "proper_running_style_nige",
        "pace_chaser": "proper_running_style_senko",
        "late_surger": "proper_running_style_sashi",
        "end_closer": "proper_running_style_oikomi",
    },
}

APTITUDE_LABELS = {1: "G", 2: "F", 3: "E", 4: "D", 5: "C", 6: "B", 7: "A", 8: "S"}


class OptimizerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AceOption:
    card_id: int
    chara_id: int
    uma_name: str
    card_name: str
    costume_name: str
    display_name: str


@dataclass(frozen=True)
class TrackOption:
    track_id: int
    name: str
    display_name: str


@dataclass(frozen=True)
class OptimizerResult:
    rankings_json_path: Path
    parent_candidates_csv_path: Path
    parent_pairs_csv_path: Path
    future_grandparents_csv_path: Path
    top_parent_candidates: tuple[dict[str, Any], ...]
    top_parent_pairs: tuple[dict[str, Any], ...]
    top_future_grandparents: tuple[dict[str, Any], ...]
    ace: dict[str, Any]
    future_parent: dict[str, Any] | None
    profile: dict[str, Any]
    scoring_weights: dict[str, Any]


def _logger_default(_message: str) -> None:
    return


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def _write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_") or "unnamed_skill"


def _quantile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _saturating_score(raw: float, scale: float) -> float:
    if raw <= 0 or scale <= 0:
        return 0.0
    return 100.0 * (1.0 - math.exp(-raw / scale))


def _weighted_total(components: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(max(0.0, float(value)) for value in weights.values())
    if total_weight <= 0:
        return 0.0
    return sum(
        float(components.get(key, 0.0)) * max(0.0, float(weight))
        for key, weight in weights.items()
    ) / total_weight


def _mode_weights(config: dict[str, Any], mode: str) -> dict[str, float]:
    """Return the component weights for a scoring role.

    ``parent_final`` was the legacy shared mode for branches and final pairs.
    Keeping it as a fallback makes old custom profiles and tests readable while
    the default profile now exposes distinct ``parent_branch`` and
    ``parent_pair`` roles.
    """
    modes = config.get("mode_weights") or {}
    selected = modes.get(mode)
    if isinstance(selected, dict) and selected:
        return selected
    if mode in {"parent_branch", "parent_pair"}:
        legacy = modes.get("parent_final")
        if isinstance(legacy, dict):
            return legacy
    return {}


def _score_breakdown(components: dict[str, float], weights: dict[str, float]) -> dict[str, Any]:
    total_weight = sum(max(0.0, float(value)) for value in weights.values()) or 1.0
    rows: dict[str, Any] = {}
    for key, raw_weight in weights.items():
        normalized_weight = max(0.0, float(raw_weight)) / total_weight
        component_score = float(components.get(key, 0.0))
        rows[key] = {
            "component_score": round(component_score, 6),
            "weight": round(normalized_weight, 6),
            "points": round(component_score * normalized_weight, 6),
        }
    return {
        "formula": "global score = sum(component score × normalized component weight)",
        "components": rows,
        "total": round(sum(item["points"] for item in rows.values()), 6),
    }


def _piecewise_score(raw: float, points: Iterable[Iterable[float]]) -> float:
    ordered = sorted((float(pair[0]), float(pair[1])) for pair in points)
    if not ordered:
        return 0.0
    if raw <= ordered[0][0]:
        return ordered[0][1]
    for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
        if raw <= x1:
            if x1 == x0:
                return y1
            ratio = (raw - x0) / (x1 - x0)
            return y0 + ratio * (y1 - y0)
    return ordered[-1][1]


def _text_map(connection: sqlite3.Connection, category: int) -> dict[int, str]:
    return {
        int(row[0]): str(row[1])
        for row in connection.execute(
            "SELECT `index`, text FROM text_data WHERE category = ?", (category,)
        )
    }


def load_ace_options(master_path: str | Path) -> list[AceOption]:
    master = Path(master_path).expanduser().resolve()
    if not master.is_file():
        raise OptimizerError(f"MDB introuvable : {master}")
    connection = sqlite3.connect(master)
    try:
        card_names = _text_map(connection, 4)
        costume_names = _text_map(connection, 5)
        chara_names = _text_map(connection, 6)
        rows = connection.execute(
            "SELECT id, chara_id FROM card_data ORDER BY chara_id, id"
        ).fetchall()
        options: list[AceOption] = []
        for card_id, chara_id in rows:
            card_id = int(card_id)
            chara_id = int(chara_id)
            uma_name = chara_names.get(chara_id, f"Chara {chara_id}")
            card_name = card_names.get(card_id, f"Card {card_id}")
            costume = costume_names.get(card_id, "")
            options.append(
                AceOption(
                    card_id=card_id,
                    chara_id=chara_id,
                    uma_name=uma_name,
                    card_name=card_name,
                    costume_name=costume,
                    display_name=f"{uma_name} — {card_name} ({card_id})",
                )
            )
        options.sort(
            key=lambda option: (
                option.uma_name.casefold(),
                option.card_name.casefold(),
                option.card_id,
            )
        )
        return options
    finally:
        connection.close()


def load_track_options(master_path: str | Path) -> list[TrackOption]:
    master = Path(master_path).expanduser().resolve()
    if not master.is_file():
        raise OptimizerError(f"MDB introuvable : {master}")
    connection = sqlite3.connect(master)
    try:
        names = _text_map(connection, 35)
        rows = connection.execute("SELECT id FROM race_track ORDER BY id").fetchall()
        return [
            TrackOption(
                track_id=int(row[0]),
                name=names.get(int(row[0]), f"Track {int(row[0])}"),
                display_name=f"{names.get(int(row[0]), f'Track {int(row[0])}')} ({int(row[0])})",
            )
            for row in rows
        ]
    finally:
        connection.close()


class AffinityResolver:
    def __init__(self, master_path: Path):
        self.connection = sqlite3.connect(master_path)
        self.connection.row_factory = sqlite3.Row
        required = {"succession_relation", "succession_relation_member", "card_data", "card_rarity_data"}
        available = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = sorted(required - available)
        if missing:
            raise OptimizerError(f"Tables MDB manquantes : {', '.join(missing)}")

        self.relation_points = {
            int(row["relation_type"]): int(row["relation_point"])
            for row in self.connection.execute("SELECT * FROM succession_relation")
        }
        memberships: dict[int, set[int]] = {}
        for row in self.connection.execute("SELECT relation_type, chara_id FROM succession_relation_member"):
            memberships.setdefault(int(row["chara_id"]), set()).add(int(row["relation_type"]))
        self.memberships = memberships

        self.card_to_chara = {
            int(row["id"]): int(row["chara_id"])
            for row in self.connection.execute("SELECT id, chara_id FROM card_data")
        }
        self.card_names = _text_map(self.connection, 4)
        self.costume_names = _text_map(self.connection, 5)
        self.chara_names = _text_map(self.connection, 6)
        self.track_names = _text_map(self.connection, 35)
        self.track_name_to_id = {name.lower(): track_id for track_id, name in self.track_names.items()}

    def close(self) -> None:
        self.connection.close()

    def pair(self, chara_a: int, chara_b: int) -> int:
        # The trainee cannot gain compatibility from herself as a sub-legacy.
        # A raw group intersection would otherwise incorrectly award every group
        # the duplicated character belongs to.
        if chara_a <= 0 or chara_b <= 0 or chara_a == chara_b:
            return 0
        common = self.memberships.get(chara_a, set()) & self.memberships.get(chara_b, set())
        return sum(self.relation_points.get(group, 0) for group in common)

    def triple(self, chara_a: int, chara_b: int, chara_c: int) -> int:
        if min(chara_a, chara_b, chara_c) <= 0 or len({chara_a, chara_b, chara_c}) < 3:
            return 0
        common = (
            self.memberships.get(chara_a, set())
            & self.memberships.get(chara_b, set())
            & self.memberships.get(chara_c, set())
        )
        return sum(self.relation_points.get(group, 0) for group in common)

    def card_details(self, card_id: int) -> dict[str, Any]:
        chara_id = self.card_to_chara.get(card_id)
        if chara_id is None:
            raise OptimizerError(f"Card inconnue dans le MDB courant : {card_id}")
        return {
            "card_id": card_id,
            "chara_id": chara_id,
            "uma_name": self.chara_names.get(chara_id, f"Chara {chara_id}"),
            "card_name": self.card_names.get(card_id, f"Card {card_id}"),
            "costume_name": self.costume_names.get(card_id, ""),
        }

    def ace_details(self, card_id: int, surface: str, distance: str, style: str) -> dict[str, Any]:
        chara_id = self.card_to_chara.get(card_id)
        if chara_id is None:
            raise OptimizerError(f"Card Ace inconnue dans le MDB courant : {card_id}")
        row = self.connection.execute(
            "SELECT * FROM card_rarity_data WHERE card_id = ? ORDER BY rarity DESC LIMIT 1",
            (card_id,),
        ).fetchone()
        if row is None:
            raise OptimizerError(f"Aptitudes introuvables pour la card Ace {card_id}")
        aptitudes = {
            dimension: int(row[columns[key]])
            for dimension, columns, key in (
                ("surface", APTITUDE_COLUMNS["surface"], surface),
                ("distance", APTITUDE_COLUMNS["distance"], distance),
                ("style", APTITUDE_COLUMNS["style"], style),
            )
        }
        return {
            "card_id": card_id,
            "chara_id": chara_id,
            "uma_name": self.chara_names.get(chara_id, f"Chara {chara_id}"),
            "card_name": self.card_names.get(card_id, f"Card {card_id}"),
            "costume_name": self.costume_names.get(card_id, ""),
            "target_aptitudes": {
                key: {"rank": value, "label": APTITUDE_LABELS.get(value, str(value))}
                for key, value in aptitudes.items()
            },
        }


def _factor_list(member: dict[str, Any] | None, factor_type: str) -> list[dict[str, Any]]:
    if not member:
        return []
    factors = member.get("factors") or {}
    return list((factors.get("by_type") or {}).get(factor_type) or [])


def _member_g1(member: dict[str, Any] | None) -> set[str]:
    if not member:
        return set()
    return set((member.get("g1_wins") or {}).get("names") or [])


def _lineage_members(
    veteran: dict[str, Any],
    role_prefix: str | None = None,
) -> list[tuple[dict[str, Any], str, str]]:
    """Return the visible parent branch with stable, optionally unique role ids."""
    lineage = veteran.get("when_used_as_parent") or {}
    parent_role = role_prefix or "parent"
    gp1_role = f"{role_prefix}_grandparent_1" if role_prefix else "grandparent_1"
    gp2_role = f"{role_prefix}_grandparent_2" if role_prefix else "grandparent_2"
    result: list[tuple[dict[str, Any], str, str]] = [(veteran, "parent", parent_role)]
    gp1 = lineage.get("grandparent_1")
    gp2 = lineage.get("grandparent_2")
    if gp1:
        result.append((gp1, "grandparent", gp1_role))
    if gp2:
        result.append((gp2, "grandparent", gp2_role))
    return result


def _condition_values(selected_values: Any) -> tuple[int | float, ...]:
    """Normalize GUI, preset and CLI condition values to an iterable.

    Course presets commonly store a single integer while the optimizer's normal
    path materializes values as sets. Keeping normalization at the comparison
    boundary makes every caller safe, including Transfer Helper contexts.
    """
    if selected_values is None or selected_values == "":
        return ()
    if isinstance(selected_values, (list, tuple, set, frozenset)):
        return tuple(selected_values)
    return (selected_values,)


def _compare_condition(selected_values: Any, operator: str, expected: int | float) -> bool:
    values = _condition_values(selected_values)
    if not values:
        return False
    if operator == "==":
        return any(value == expected for value in values)
    if operator == "!=":
        return all(value != expected for value in values)
    if operator == ">=":
        return all(value >= expected for value in values)
    if operator == "<=":
        return all(value <= expected for value in values)
    if operator == ">":
        return all(value > expected for value in values)
    if operator == "<":
        return all(value < expected for value in values)
    return True


def _compile_static_condition_rules(skill_catalog: dict[str, Any]) -> dict[str, list[list[list[list[dict[str, Any]]]]]]:
    rules: dict[str, list[list[list[list[dict[str, Any]]]]]] = {}
    for skill in skill_catalog.get("skills") or []:
        white = skill.get("white_spark") or {}
        key = str(white.get("catalog_key") or "")
        if not key:
            continue
        activations: list[list[list[list[dict[str, Any]]]]] = []
        for activation in skill.get("activations") or []:
            fields: list[list[list[dict[str, Any]]]] = []
            for field_name in ("precondition", "condition"):
                field = activation.get(field_name) or {}
                groups: list[list[dict[str, Any]]] = []
                for group in field.get("or_groups") or []:
                    static_atoms = [
                        atom
                        for atom in group
                        if atom.get("parsed")
                        and atom.get("category") == "course_static"
                        and atom.get("variable")
                    ]
                    if static_atoms:
                        groups.append(static_atoms)
                if groups:
                    fields.append(groups)
            if fields:
                activations.append(fields)
        if activations:
            rules[key] = activations
    return rules


def _static_condition_state(
    activations: list[list[list[list[dict[str, Any]]]]],
    course_conditions: dict[str, set[int]],
) -> str:
    """Return matched, mismatched or unknown for course-static conditions."""
    any_possible = False
    any_fully_resolved = False
    for fields in activations:
        activation_possible = True
        activation_resolved = True
        for groups in fields:
            field_possible = False
            field_resolved_match = False
            for group in groups:
                group_possible = True
                group_resolved = True
                for atom in group:
                    variable = str(atom.get("variable") or "")
                    selected = course_conditions.get(variable)
                    if not selected:
                        group_resolved = False
                        continue
                    if not _compare_condition(selected, str(atom.get("operator") or "=="), atom.get("value")):
                        group_possible = False
                        break
                if group_possible:
                    field_possible = True
                    if group_resolved:
                        field_resolved_match = True
            if not field_possible:
                activation_possible = False
                break
            if not field_resolved_match:
                activation_resolved = False
        if activation_possible:
            any_possible = True
            if activation_resolved:
                any_fully_resolved = True
    if any_fully_resolved:
        return "matched"
    if any_possible:
        return "unknown"
    return "mismatched"


def _matched_static_green_adjustment(
    activations: list[list[list[list[dict[str, Any]]]]],
    course_conditions: dict[str, set[int]],
    values: dict[str, float],
    modes: dict[str, str],
    fallback: float,
) -> tuple[float, str]:
    candidates: list[tuple[float, str]] = [(float(fallback), "floor")]
    for fields in activations:
        for groups in fields:
            for group in groups:
                for atom in group:
                    variable = str(atom.get("variable") or "")
                    selected = course_conditions.get(variable)
                    if not selected:
                        continue
                    expected = atom.get("value")
                    if not _compare_condition(selected, str(atom.get("operator") or "=="), expected):
                        continue
                    if variable == "rotation":
                        key = "rotation_right" if int(expected) == 1 else "rotation_left"
                    else:
                        key = variable
                    candidates.append((float(values.get(key, fallback)), str(modes.get(key, "floor"))))
    return max(candidates, key=lambda item: item[0])


def _selected_weight_lookup(
    weights_payload: dict[str, Any],
    course_payload: dict[str, Any] | None,
    skill_catalog: dict[str, Any],
    surface: str,
    distance: str,
    style: str,
    course_key: str | None,
    course_conditions: dict[str, set[int]],
    active_green_floor: float,
    green_floors: dict[str, float],
    green_modes: dict[str, str],
) -> tuple[Callable[[str], float], str, dict[str, int]]:
    generic_skills = weights_payload.get("skills") or {}
    course_skills: dict[str, Any] | None = None
    source_label = "generic"
    if course_key and course_payload:
        course = (course_payload.get("courses") or {}).get(course_key)
        if course:
            course_profile = course.get("profile") or {}
            if course_profile.get("surface") != surface or course_profile.get("distance") != distance:
                raise OptimizerError(
                    f"Le preset {course_key!r} ne correspond pas au profil {surface}/{distance}."
                )
            course_skills = (((course.get("style_weights") or {}).get(style) or {}).get("skills") or {})
            source_label = str(course.get("label") or course_key)

    static_rules = _compile_static_condition_rules(skill_catalog)
    diagnostics = {"matched": 0, "mismatched": 0, "unknown": 0, "not_static": 0}
    state_cache: dict[str, str] = {}
    diagnostic_seen: set[str] = set()

    def lookup(catalog_key: str) -> float:
        if course_skills is not None:
            cell = course_skills.get(catalog_key) or {}
            value = cell.get("weight")
        else:
            value = None
        if value is None:
            skill = generic_skills.get(catalog_key) or {}
            cell = (((skill.get("weight_matrix") or {}).get(surface) or {}).get(distance) or {}).get(style) or {}
            value = cell.get("weight")
        base = max(0.0, float(value)) if value is not None else 0.0

        activations = static_rules.get(catalog_key)
        if not activations:
            state = "not_static"
        else:
            state = state_cache.get(catalog_key)
            if state is None:
                state = _static_condition_state(activations, course_conditions)
                state_cache[catalog_key] = state
        if catalog_key not in diagnostic_seen:
            diagnostics[state] = diagnostics.get(state, 0) + 1
            diagnostic_seen.add(catalog_key)
        if state == "mismatched":
            return 0.0
        if state == "matched":
            contextual_value, mode = _matched_static_green_adjustment(
                activations or [], course_conditions, green_floors, green_modes, active_green_floor
            )
            return contextual_value if mode == "override" else max(base, contextual_value)
        return base

    return lookup, source_label, diagnostics


def _race_skill_map(race_catalog: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entry in race_catalog.get("race_factors") or []:
        name = str(entry.get("race_factor_name") or "")
        if not name:
            continue
        result[name] = [
            slugify(str(skill.get("name") or ""))
            for skill in entry.get("granted_skills") or []
            if skill.get("name")
        ]
    return result


def _white_generation_support_score(
    lineage_members: list[tuple[dict[str, Any], str, str]],
    weight_lookup: Callable[[str], float],
    config: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """Score the incremental gene-generation support from matching white Sparks.

    This deliberately ignores whether the farming run buys the basic or gold form.
    Only the lineage-copy bonus is valued: each distinct lineage member carrying the
    same white skill Spark contributes the same incremental probability bonus.
    """
    cfg = config.get("white_generation") or {}
    bonus_per_copy = float(cfg.get("bonus_per_lineage_copy", 0.025))
    max_lineage_copies = int(cfg.get("max_lineage_copies", 6))
    saturation = float(cfg.get("saturation", 0.18))

    presence: dict[str, dict[str, Any]] = {}
    for member, _position, role in lineage_members:
        seen_for_member: set[str] = set()
        for factor in _factor_list(member, "white_skill"):
            key = slugify(str(factor.get("name") or ""))
            if not key or key in seen_for_member:
                continue
            seen_for_member.add(key)
            item = presence.setdefault(key, {"count": 0, "roles": [], "name": factor.get("name")})
            item["count"] += 1
            item["roles"].append(role)

    raw = 0.0
    details: list[dict[str, Any]] = []
    for key, item in presence.items():
        profile_weight = max(0.0, float(weight_lookup(key)))
        count = min(max_lineage_copies, int(item["count"]))
        lineage_bonus = bonus_per_copy * count
        contribution = profile_weight * lineage_bonus
        raw += contribution
        details.append({
            "name": item.get("name"),
            "catalog_key": key,
            "lineage_copy_count": count,
            "roles": item.get("roles") or [],
            "profile_weight": round(profile_weight, 6),
            "bonus_per_lineage_copy": round(bonus_per_copy, 6),
            "lineage_generation_bonus": round(lineage_bonus, 6),
            "contribution": round(contribution, 6),
        })
    details.sort(key=lambda item: item["contribution"], reverse=True)
    score = _saturating_score(raw, saturation)
    return score, {
        "raw": raw,
        "scale": saturation,
        "formula": "100 × (1 - exp(-sum(profile weight × lineage-copy bonus) / saturation))",
        "assumption": "Only the incremental lineage bonus is valued. Basic/◎/gold learned form and base gene-generation chance are intentionally ignored.",
        "scope": "Only white skill Sparks from the candidate and its two current parents. Race/scenario Sparks are excluded.",
        "bonus_per_lineage_copy": bonus_per_copy,
        "skills": details[:30],
        "skill_count": len(details),
    }

def _blue_score(
    members: list[tuple[dict[str, Any], str, str]],
    distance: str,
    config: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    stat_weights = (config.get("blue_stat_weights_by_distance") or {}).get(distance) or {}
    quality_by_stars = config.get("blue_star_quality") or {"1": 0.12, "2": 0.78, "3": 1.0}
    influence_by_distance = config.get("blue_score_influence_by_distance") or {
        "sprint": 0.45,
        "mile": 0.65,
        "medium": 0.90,
        "long": 1.00,
    }
    influence = max(0.0, float(influence_by_distance.get(distance, 1.0)))
    neutral_score = max(0.0, min(100.0, float(config.get("blue_neutral_score", 50.0))))
    raw = 0.0
    slot_count = max(1, len(members))
    details: list[dict[str, Any]] = []
    for member, _position, role in members:
        factors = _factor_list(member, "blue_stat")
        if not factors:
            details.append({"role": role, "name": None, "stars": 0, "quality": 0.0, "relevance": 0.0, "contribution": 0.0})
            continue
        for factor in factors:
            stars = int(factor.get("stars") or 0)
            name = str(factor.get("name") or "")
            quality = float(quality_by_stars.get(str(stars), 0.0))
            relevance = float(stat_weights.get(name, 0.0))
            contribution = quality * relevance
            raw += contribution
            details.append({
                "role": role,
                "name": name,
                "stars": stars,
                "quality": round(quality, 4),
                "relevance": round(relevance, 4),
                "contribution": round(contribution, 4),
            })
    uncompressed_score = min(100.0, 100.0 * raw / slot_count)
    # Shorter distances make the target stat line easier to reach, so lineage
    # blue quality should differentiate candidates less strongly. Blending
    # toward a neutral score preserves cross-profile comparability while
    # compressing the impact of good/bad blues where appropriate.
    score = max(0.0, min(100.0, neutral_score + influence * (uncompressed_score - neutral_score)))
    return score, {
        "raw": raw,
        "slot_count": slot_count,
        "uncompressed_score": round(uncompressed_score, 6),
        "distance_influence": round(influence, 6),
        "neutral_score": round(neutral_score, 6),
        "formula": (
            "raw blue score = 100 × sum(star-tier quality × stat relevance) / lineage slots; "
            "final score = neutral + distance influence × (raw score - neutral)"
        ),
        "star_tiers": quality_by_stars,
        "stat_weights": stat_weights,
        "factors": details,
    }


def _initial_rank_gain(total_stars: int) -> int:
    """Return aptitude ranks gained at run start from matching red stars."""
    stars = max(0, int(total_stars))
    if stars <= 0:
        return 0
    return min(4, 1 + (stars - 1) // 3)


def _initial_aptitude_rank(base_rank: int, total_stars: int) -> int:
    # Initial inheritance cannot start an aptitude at S.
    return min(7, max(1, int(base_rank)) + _initial_rank_gain(total_stars))


def _stars_required_to_start_at_a(base_rank: int) -> int:
    rank = max(1, int(base_rank))
    if rank >= 7:
        return 0
    # B→A needs 1★. Every lower rank needs three more stars.
    return 1 + 3 * (6 - rank)


def _poisson_binomial_distribution(probabilities: Iterable[float]) -> list[float]:
    """Exact distribution for independent, non-identical Bernoulli trials."""
    distribution = [1.0]
    for raw_probability in probabilities:
        probability = max(0.0, min(1.0, float(raw_probability)))
        updated = [0.0] * (len(distribution) + 1)
        for successes, mass in enumerate(distribution):
            updated[successes] += mass * (1.0 - probability)
            updated[successes + 1] += mass * probability
        distribution = updated
    return distribution


def _probability_at_least(distribution: list[float], successes: int) -> float:
    required = max(0, int(successes))
    if required <= 0:
        return 1.0
    if required >= len(distribution):
        return 0.0
    return max(0.0, min(1.0, sum(distribution[required:])))


def _aptitude_proc_rate(stars: int, affinity: float, config: dict[str, Any]) -> tuple[float, float]:
    aptitude_cfg = config.get("aptitude_inheritance") or {}
    rates = aptitude_cfg.get("pink_base_proc_rates") or {"1": 0.01, "2": 0.03, "3": 0.05}
    base_rate = max(0.0, float(rates.get(str(int(stars)), 0.0)))
    effective = min(1.0, base_rate * (1.0 + max(0.0, float(affinity)) / 100.0))
    return base_rate, effective


def _aptitude_pair_score(
    dimension: str,
    initial_rank: int,
    probability_a: float,
    probability_s: float,
    config: dict[str, Any],
) -> float:
    aptitude_cfg = config.get("aptitude_inheritance") or {}
    dimension_cfg = aptitude_cfg.get(dimension) or {}
    s_probability_curve = dimension_cfg.get("s_probability_curve") or [[0.0, 0.0], [1.0, 100.0]]
    s_probability_quality = max(
        0.0,
        min(1.0, _piecewise_score(probability_s, s_probability_curve) / 100.0),
    )
    if initial_rank >= 7:
        if dimension == "distance" and probability_s <= 0.0:
            return 0.0
        base = float(dimension_cfg.get("start_a_base_score", {"distance": 70, "surface": 80, "style": 90}[dimension]))
        s_weight = float(dimension_cfg.get("start_a_s_probability_weight", {"distance": 30, "surface": 20, "style": 10}[dimension]))
        return max(0.0, min(100.0, base + s_weight * s_probability_quality))
    if initial_rank == 6:
        base = float(dimension_cfg.get("start_b_base_score", {"distance": 20, "surface": 55, "style": 70}[dimension]))
        a_weight = float(dimension_cfg.get("start_b_a_probability_weight", {"distance": 45, "surface": 30, "style": 25}[dimension]))
        s_weight = float(dimension_cfg.get("start_b_s_probability_weight", {"distance": 35, "surface": 15, "style": 5}[dimension]))
        return max(0.0, min(100.0, base + a_weight * probability_a + s_weight * s_probability_quality))
    below_cfg = dimension_cfg.get("below_b") or {}
    base = float(below_cfg.get("base_score", 0 if dimension == "distance" else 10))
    a_weight = float(below_cfg.get("a_probability_weight", 0 if dimension == "distance" else (25 if dimension == "surface" else 30)))
    s_weight = float(below_cfg.get("s_probability_weight", 0 if dimension == "distance" else (10 if dimension == "surface" else 5)))
    return max(0.0, min(100.0, base + a_weight * probability_a + s_weight * s_probability_quality))


def _partial_aptitude_score(
    *,
    mode: str,
    base_rank: int,
    total_stars: int,
    probability_any_proc: float,
    config: dict[str, Any],
) -> float:
    """Score one incomplete branch without pretending it is a full final pair."""
    aptitude_cfg = config.get("aptitude_inheritance") or {}
    partial_cfg = (aptitude_cfg.get("partial_scoring") or {}).get(mode) or {}
    max_stars = float(partial_cfg.get("full_star_reference", 6 if mode == "parent_branch" else 3))
    target_probability = float(partial_cfg.get("full_proc_probability", 0.40 if mode == "parent_branch" else 0.20))
    star_weight = float(partial_cfg.get("star_weight", 0.60 if mode == "parent_branch" else 0.65))
    proc_weight = float(partial_cfg.get("proc_weight", 1.0 - star_weight))
    required = _stars_required_to_start_at_a(base_rank)
    if required > 0:
        star_readiness = min(1.0, total_stars / required)
    else:
        star_readiness = min(1.0, total_stars / max(1.0, max_stars))
    proc_readiness = min(1.0, probability_any_proc / max(0.000001, target_probability))
    total_weight = max(0.000001, star_weight + proc_weight)
    return 100.0 * (star_readiness * star_weight + proc_readiness * proc_weight) / total_weight


def _distance_viability(
    *,
    mode: str,
    distance_detail: dict[str, Any],
    white_score: float = 0.0,
    blue_score: float = 0.0,
    config: dict[str, Any],
) -> dict[str, Any]:
    initial_rank = int(distance_detail.get("initial_rank") or 0)
    probability_a = float(distance_detail.get("probability_reach_a") or 0.0)
    probability_s = float(distance_detail.get("probability_reach_s") or 0.0)
    total_stars = int(distance_detail.get("total_stars") or 0)
    carrier_count = int(distance_detail.get("carrier_count") or 0)

    if mode == "parent_pair":
        distance_cfg = ((config.get("aptitude_inheritance") or {}).get("distance") or {})
        compensation = distance_cfg.get("b_compensation") or {}
        thresholds = {
            "minimum_probability_a": float(compensation.get("minimum_probability_a", 0.55)),
            "minimum_probability_s": float(compensation.get("minimum_probability_s", 0.15)),
            "minimum_white_score": float(compensation.get("minimum_white_score", 85.0)),
            "minimum_blue_score": float(compensation.get("minimum_blue_score", 75.0)),
        }
        compensation_checks = {
            "probability_a": probability_a >= thresholds["minimum_probability_a"],
            "probability_s": probability_s >= thresholds["minimum_probability_s"],
            "white_score": float(white_score) >= thresholds["minimum_white_score"],
            "blue_score": float(blue_score) >= thresholds["minimum_blue_score"],
        }
        if initial_rank >= 7 and probability_s > 0.0:
            key, tier, viable = "ready_for_s", 4, True
        elif initial_rank == 6 and all(compensation_checks.values()):
            key, tier, viable = "distance_b_compensated", 3, True
        elif initial_rank == 6:
            key, tier, viable = "distance_b_uncompensated", 1, False
        elif initial_rank >= 7:
            key, tier, viable = "no_s_support", 0, False
        else:
            key, tier, viable = "underprepared", 0, False
        return {
            "key": key,
            "tier": tier,
            "is_viable": viable,
            "sort_priority": tier,
            "scope": "final_parent_pair",
            "initial_rank": initial_rank,
            "initial_rank_label": APTITUDE_LABELS.get(initial_rank, str(initial_rank)),
            "is_initial_requirement_met": initial_rank >= 7,
            "probability_reach_a": round(probability_a, 8),
            "probability_reach_s": round(probability_s, 8),
            "compensation_thresholds": thresholds,
            "compensation_checks": compensation_checks,
            "white_score": round(float(white_score), 6),
            "blue_score": round(float(blue_score), 6),
        }

    if mode == "parent_branch":
        if carrier_count == 0:
            key, tier = "deficit", 0
        elif total_stars >= 6 and carrier_count >= 2:
            key, tier = "distance_carrier", 3
        elif total_stars >= 3:
            key, tier = "balanced", 2
        else:
            key, tier = "light", 1
        return {
            "key": key,
            "tier": tier,
            "is_viable": None,
            "sort_priority": tier,
            "scope": "parent_branch_contribution",
            "initial_rank": initial_rank,
            "initial_rank_label": APTITUDE_LABELS.get(initial_rank, str(initial_rank)),
            "is_initial_requirement_met": initial_rank >= 7,
            "probability_reach_a": round(probability_a, 8),
            "probability_reach_s": round(probability_s, 8),
        }

    return {
        "key": "matching_distance" if carrier_count else "off_distance",
        "tier": 1 if carrier_count else 0,
        "is_viable": None,
        "sort_priority": 0,
        "scope": "future_grandparent_partial_contribution",
        "initial_rank": initial_rank,
        "initial_rank_label": APTITUDE_LABELS.get(initial_rank, str(initial_rank)),
        "probability_reach_a": round(probability_a, 8),
        "probability_reach_s": round(probability_s, 8),
    }


def _future_grandparent_pink_score(
    members: list[tuple[dict[str, Any], str, str]],
    ace: dict[str, Any],
    surface: str,
    distance: str,
    style: str,
    config: dict[str, Any],
) -> tuple[float, dict[str, Any]]:
    """Score a future GP's pink Spark with the intentionally simple GP model.

    A future grandparent is only one of the six final lineage members.  This mode
    therefore values a useful/acceptable factor without trying to predict the
    final Ace's starting rank or Inspiration-event outcome.  Probability-aware
    aptitude scoring is reserved for complete parent branches and final pairs.
    """
    gp_cfg = config.get("future_grandparent_heuristics") or {}
    targets = {
        "surface": SURFACE_FACTOR_NAMES[surface],
        "distance": DISTANCE_FACTOR_NAMES[distance],
        "style": STYLE_FACTOR_NAMES[style],
    }
    dimension_weights = gp_cfg.get("pink_dimension_weights") or {
        "distance": 1.0,
        "surface": 0.72,
        "style": 0.55,
    }
    star_quality = gp_cfg.get("pink_star_quality") or {
        "1": 0.55,
        "2": 0.72,
        "3": 1.0,
    }
    need_cfg = gp_cfg.get("pink_need_multiplier") or {
        "below_a": 1.1,
        "a_or_s": 1.0,
    }
    slot_count = max(1, len(members))
    raw = 0.0
    stars_by_dimension = {key: 0 for key in targets}
    details: list[dict[str, Any]] = []
    for member, _position, role in members:
        factors = _factor_list(member, "red_aptitude")
        if not factors:
            details.append({
                "role": role,
                "name": None,
                "stars": 0,
                "matched_dimension": None,
                "contribution": 0.0,
            })
            continue
        for factor in factors:
            name = str(factor.get("name") or "")
            stars = int(factor.get("stars") or 0)
            matched_dimension = next(
                (key for key, target in targets.items() if name == target), None
            )
            quality = float(star_quality.get(str(stars), 0.0))
            dimension_weight = (
                float(dimension_weights.get(matched_dimension, 0.0))
                if matched_dimension else 0.0
            )
            base_rank = (
                int(ace["target_aptitudes"][matched_dimension]["rank"])
                if matched_dimension else 0
            )
            need_multiplier = (
                float(need_cfg.get("below_a" if base_rank < 7 else "a_or_s", 1.0))
                if matched_dimension else 0.0
            )
            contribution = (
                min(1.0, quality * dimension_weight * need_multiplier)
                if matched_dimension else 0.0
            )
            if matched_dimension:
                stars_by_dimension[matched_dimension] += stars
            raw += contribution
            details.append({
                "role": role,
                "name": name,
                "stars": stars,
                "matched_dimension": matched_dimension,
                "star_quality": round(quality, 4),
                "dimension_weight": round(dimension_weight, 4),
                "base_rank": base_rank or None,
                "base_rank_label": APTITUDE_LABELS.get(base_rank) if base_rank else None,
                "need_multiplier": round(need_multiplier, 4),
                "contribution": round(contribution, 4),
            })
    score = min(100.0, 100.0 * raw / slot_count)
    dimensions = {
        dimension: {
            "target": target_name,
            "base_rank": int(ace["target_aptitudes"][dimension]["rank"]),
            "base_rank_label": ace["target_aptitudes"][dimension]["label"],
            "matching_stars": stars_by_dimension[dimension],
            "dimension_weight": float(dimension_weights.get(dimension, 0.0)),
        }
        for dimension, target_name in targets.items()
    }
    return score, {
        "raw": raw,
        "slot_count": slot_count,
        "formula": "100 × sum(star quality × aptitude relevance × need multiplier) / evaluated GP slots",
        "model": "future_grandparent_simple",
        "uses_proc_probability": False,
        "star_tiers": star_quality,
        "dimensions": dimensions,
        "factors": details,
    }


def _future_grandparent_white_score(
    members: list[tuple[dict[str, Any], str, str]],
    weight_lookup: Callable[[str], float],
    config: dict[str, Any],
    race_skill_map: dict[str, list[str]] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Score direct useful factors on a future GP without affinity proc maths.

    Direct white Skill Sparks keep the historical star/position heuristic. Race
    Sparks that grant the same skill use the same heuristic multiplied by their
    base proc-rate ratio versus a white Skill Spark of the same star count.
    """
    gp_cfg = config.get("future_grandparent_heuristics") or {}
    position_weights = config.get("position_transmission") or {}
    star_quality = gp_cfg.get("white_star_quality") or {
        "1": 1.0,
        "2": 1.35,
        "3": 1.8,
    }
    white_cfg = config.get("white_inheritance") or {}
    white_rates = white_cfg.get("base_proc_rates") or {"1": 0.03, "2": 0.06, "3": 0.09}
    race_rates = white_cfg.get("race_base_proc_rates") or {"1": 0.01, "2": 0.02, "3": 0.03}
    granted_by_race = race_skill_map or {}

    raw = 0.0
    details: list[dict[str, Any]] = []
    for member, position, role in members:
        position_weight = float(position_weights.get(position, 1.0))
        for factor in _factor_list(member, "white_skill"):
            stars = int(factor.get("stars") or 0)
            name = str(factor.get("name") or "")
            catalog_key = slugify(name)
            profile_weight = max(0.0, float(weight_lookup(catalog_key)))
            quality = float(star_quality.get(str(stars), 0.0))
            contribution = profile_weight * quality * position_weight
            raw += contribution
            details.append({
                "role": role,
                "position": position,
                "source_type": "white_skill",
                "source_factor_name": name,
                "name": name,
                "catalog_key": catalog_key,
                "stars": stars,
                "profile_weight": round(profile_weight, 6),
                "star_quality": round(quality, 6),
                "position_weight": round(position_weight, 6),
                "proc_rate_ratio_vs_white": 1.0,
                "contribution": round(contribution, 8),
            })

        for factor in _factor_list(member, "white_race"):
            stars = int(factor.get("stars") or 0)
            race_name = str(factor.get("name") or "")
            quality = float(star_quality.get(str(stars), 0.0))
            white_rate = max(0.0, float(white_rates.get(str(stars), 0.0)))
            race_rate = max(0.0, float(race_rates.get(str(stars), 0.0)))
            rate_ratio = race_rate / white_rate if white_rate > 0.0 else 0.0
            for catalog_key in granted_by_race.get(race_name, []):
                profile_weight = max(0.0, float(weight_lookup(catalog_key)))
                contribution = profile_weight * quality * position_weight * rate_ratio
                raw += contribution
                details.append({
                    "role": role,
                    "position": position,
                    "source_type": "white_race",
                    "source_factor_name": race_name,
                    "name": catalog_key,
                    "catalog_key": catalog_key,
                    "stars": stars,
                    "profile_weight": round(profile_weight, 6),
                    "star_quality": round(quality, 6),
                    "position_weight": round(position_weight, 6),
                    "white_base_proc_rate": round(white_rate, 8),
                    "race_base_proc_rate": round(race_rate, 8),
                    "proc_rate_ratio_vs_white": round(rate_ratio, 8),
                    "contribution": round(contribution, 8),
                })
    scale = float((config.get("white_saturation") or {}).get("future_grandparent", 1.0))
    details.sort(key=lambda item: item["contribution"], reverse=True)
    return _saturating_score(raw, scale), {
        "raw": raw,
        "scale": scale,
        "formula": "direct white: priority × star quality × GP position; granted race skill: same value × race/white base proc-rate ratio; then diminishing-return saturation",
        "model": "future_grandparent_simple",
        "uses_individual_affinity": False,
        "uses_simplified_race_proc_ratio": True,
        "white_base_proc_rates": white_rates,
        "race_base_proc_rates": race_rates,
        "star_tiers": star_quality,
        "top_factors": details[:30],
        "factor_count": len(details),
    }


def _pink_score(
    members: list[tuple[dict[str, Any], str, str]],
    ace: dict[str, Any],
    surface: str,
    distance: str,
    style: str,
    config: dict[str, Any],
    mode: str = "parent_branch",
    inheritance_affinities: dict[str, float] | None = None,
) -> tuple[float, dict[str, Any]]:
    targets = {
        "surface": SURFACE_FACTOR_NAMES[surface],
        "distance": DISTANCE_FACTOR_NAMES[distance],
        "style": STYLE_FACTOR_NAMES[style],
    }
    affinities = inheritance_affinities or {}
    aptitude_cfg = config.get("aptitude_inheritance") or {}
    event_count = max(1, int(aptitude_cfg.get("inspiration_event_count", 2)))
    mode_dimension_weights = (
        ((aptitude_cfg.get("dimension_weights_by_mode") or {}).get(mode))
        or {
            "distance": 0.72 if mode == "parent_pair" else (0.65 if mode == "parent_branch" else 0.55),
            "surface": 0.18 if mode == "parent_pair" else (0.22 if mode == "parent_branch" else 0.27),
            "style": 0.10 if mode == "parent_pair" else (0.13 if mode == "parent_branch" else 0.18),
        }
    )
    dimensions_work: dict[str, dict[str, Any]] = {
        dimension: {
            "target": target,
            "total_stars": 0,
            "carrier_roles": set(),
            "parent_carrier_roles": set(),
            "trial_probabilities": [],
            "factors": [],
        }
        for dimension, target in targets.items()
    }
    factor_rows: list[dict[str, Any]] = []

    for member, position, role in members:
        factors = _factor_list(member, "red_aptitude")
        if not factors:
            factor_rows.append({
                "role": role,
                "position": position,
                "name": None,
                "stars": 0,
                "matched_dimension": None,
                "inheritance_affinity": round(float(affinities.get(role, 0.0)), 4),
                "base_proc_rate": 0.0,
                "proc_probability_per_event": 0.0,
            })
            continue
        for factor in factors:
            name = str(factor.get("name") or "")
            stars = int(factor.get("stars") or 0)
            matched_dimension = next((key for key, target in targets.items() if name == target), None)
            affinity_value = max(0.0, float(affinities.get(role, 0.0)))
            base_rate, proc_rate = _aptitude_proc_rate(stars, affinity_value, config) if matched_dimension else (0.0, 0.0)
            row = {
                "role": role,
                "position": position,
                "name": name,
                "stars": stars,
                "matched_dimension": matched_dimension,
                "inheritance_affinity": round(affinity_value, 4),
                "base_proc_rate": round(base_rate, 8),
                "affinity_multiplier": round(1.0 + affinity_value / 100.0, 6),
                "proc_probability_per_event": round(proc_rate, 8),
                "proc_probability_over_run": round(1.0 - (1.0 - proc_rate) ** event_count, 8),
            }
            factor_rows.append(row)
            if not matched_dimension:
                continue
            work = dimensions_work[matched_dimension]
            work["total_stars"] += stars
            work["carrier_roles"].add(role)
            if position == "parent":
                work["parent_carrier_roles"].add(role)
            work["trial_probabilities"].extend([proc_rate] * event_count)
            work["factors"].append(row)

    dimensions: dict[str, dict[str, Any]] = {}
    for dimension, work in dimensions_work.items():
        base_rank = int(ace["target_aptitudes"][dimension]["rank"])
        total_stars = int(work["total_stars"])
        initial_rank = _initial_aptitude_rank(base_rank, total_stars)
        required_a = max(0, 7 - initial_rank)
        required_s = max(0, 8 - initial_rank)
        distribution = _poisson_binomial_distribution(work["trial_probabilities"])
        probability_a = _probability_at_least(distribution, required_a)
        probability_s = _probability_at_least(distribution, required_s)
        probability_any = _probability_at_least(distribution, 1)
        dimension_cfg = aptitude_cfg.get(dimension) or {}
        s_probability_curve = dimension_cfg.get("s_probability_curve") or [[0.0, 0.0], [1.0, 100.0]]
        s_probability_quality = max(
            0.0,
            min(100.0, _piecewise_score(probability_s, s_probability_curve)),
        )
        if mode == "parent_pair":
            score = _aptitude_pair_score(
                dimension, initial_rank, probability_a, probability_s, config
            )
        else:
            score = _partial_aptitude_score(
                mode=mode,
                base_rank=base_rank,
                total_stars=total_stars,
                probability_any_proc=probability_any,
                config=config,
            )
        dimensions[dimension] = {
            "target": targets[dimension],
            "score": round(score, 6),
            "base_rank": base_rank,
            "base_rank_label": APTITUDE_LABELS.get(base_rank, str(base_rank)),
            "total_stars": total_stars,
            "initial_rank_gain": _initial_rank_gain(total_stars),
            "initial_rank": initial_rank,
            "initial_rank_label": APTITUDE_LABELS.get(initial_rank, str(initial_rank)),
            "stars_required_to_start_at_a": _stars_required_to_start_at_a(base_rank),
            "starts_at_a": initial_rank >= 7,
            "procs_required_for_a": required_a,
            "procs_required_for_s": required_s,
            "probability_any_proc": round(probability_any, 8),
            "probability_reach_a": round(probability_a, 8),
            "probability_reach_s": round(probability_s, 8),
            "probability_reach_s_quality": round(s_probability_quality, 6),
            "s_probability_curve": s_probability_curve,
            "proc_count_distribution": [round(value, 10) for value in distribution],
            "carrier_count": len(work["carrier_roles"]),
            "carrier_roles": sorted(work["carrier_roles"]),
            "parent_carrier_count": len(work["parent_carrier_roles"]),
            "sum_proc_probability_per_event": round(sum(prob for prob in work["trial_probabilities"][::event_count]), 8) if event_count else 0.0,
            "inspiration_event_count": event_count,
            "factors": work["factors"],
            "formula": (
                "initial rank from total matching stars; each matching factor rolls independently at every inspiration event; "
                "p = base pink rate × (1 + individual inheritance affinity / 100); one proc equals one aptitude rank"
            ),
        }

    distance_detail = dimensions["distance"]
    # Backward-compatible names retained for CSV/UI consumers.
    distance_detail["activation_score"] = round(100.0 * float(distance_detail["probability_reach_s"]), 6)
    distance_detail["weighted_support"] = distance_detail["sum_proc_probability_per_event"]
    distance_detail["initial_required_stars"] = distance_detail["stars_required_to_start_at_a"]
    distance_detail["initial_readiness"] = 1.0 if distance_detail["starts_at_a"] else 0.0
    distance_detail["star_tiers"] = aptitude_cfg.get("pink_base_proc_rates") or {"1": 0.01, "2": 0.03, "3": 0.05}
    distance_detail["position_weights"] = None
    distance_detail["viability"] = _distance_viability(
        mode=mode,
        distance_detail=distance_detail,
        config=config,
    )

    dimension_weight_total = sum(max(0.0, float(value)) for value in mode_dimension_weights.values()) or 1.0
    overall_score = sum(
        float(dimensions[key]["score"]) * max(0.0, float(mode_dimension_weights.get(key, 0.0)))
        for key in ("distance", "surface", "style")
    ) / dimension_weight_total
    other_weight_total = sum(max(0.0, float(mode_dimension_weights.get(key, 0.0))) for key in ("surface", "style")) or 1.0
    other_score = sum(
        float(dimensions[key]["score"]) * max(0.0, float(mode_dimension_weights.get(key, 0.0)))
        for key in ("surface", "style")
    ) / other_weight_total

    return overall_score, {
        "raw": overall_score,
        "slot_count": max(1, len(members)),
        "formula": "probability-aware aptitude model; distance, surface and style are evaluated independently",
        "dimension_weights": mode_dimension_weights,
        "dimensions": dimensions,
        "factors": factor_rows,
        "distance_s": distance_detail,
        "pink_other": {
            "score": round(other_score, 6),
            "dimensions": ["surface", "style"],
            "surface": dimensions["surface"],
            "style": dimensions["style"],
            "formula": "weighted surface/style aptitude quality; distance is excluded and scored separately",
        },
    }

def _white_score(
    members: list[tuple[dict[str, Any], str, str]],
    weight_lookup: Callable[[str], float],
    config: dict[str, Any],
    saturation_key: str,
    inheritance_affinities: dict[str, float] | None = None,
    race_skill_map: dict[str, list[str]] | None = None,
) -> tuple[float, dict[str, Any]]:
    """Score useful inherited skills from direct white and Race Sparks.

    Both source types use their actual base proc rate, the carrier's individual
    affinity and the same two Inspiration Events. Sources granting the same skill
    are merged into one P(inherited at least once), so Race Sparks need no extra
    arbitrary discount beyond their naturally lower 1/2/3% base rates.
    """
    white_cfg = config.get("white_inheritance") or {}
    base_rates = white_cfg.get("base_proc_rates") or {"1": 0.03, "2": 0.06, "3": 0.09}
    race_base_rates = white_cfg.get("race_base_proc_rates") or {"1": 0.01, "2": 0.02, "3": 0.03}
    event_count = max(1, int(white_cfg.get("inspiration_event_count", 2) or 2))
    per_event_cap = max(0.0, min(float(white_cfg.get("per_event_probability_cap", 1.0)), 1.0))
    distinct_skill_curve = white_cfg.get("distinct_skill_probability_curve") or [
        [0.0, 0.0],
        [0.10, 0.10],
        [0.20, 0.30],
        [0.40, 0.52],
        [0.60, 0.64],
        [0.80, 0.70],
        [1.0, 0.73],
    ]
    affinities = inheritance_affinities or {}
    granted_by_race = race_skill_map or {}

    grouped: dict[str, dict[str, Any]] = {}
    factor_details: list[dict[str, Any]] = []

    def register_source(
        *,
        role: str,
        position: str,
        skill_key: str,
        skill_name: str,
        source_type: str,
        source_factor_name: str,
        stars: int,
        base_rate: float,
        affinity_value: float,
    ) -> None:
        affinity_multiplier = 1.0 + affinity_value / 100.0
        profile_weight = max(0.0, float(weight_lookup(skill_key)))
        probability_per_event = min(per_event_cap, max(0.0, base_rate) * affinity_multiplier)
        probability_over_run = 1.0 - (1.0 - probability_per_event) ** event_count
        standalone_contribution = profile_weight * probability_over_run
        row = {
            "role": role,
            "position": position,
            "source_type": source_type,
            "source_factor_name": source_factor_name,
            "name": skill_name,
            "catalog_key": skill_key,
            "stars": stars,
            "profile_weight": round(profile_weight, 6),
            "inheritance_affinity": round(affinity_value, 6),
            "base_proc_rate": round(base_rate, 8),
            "affinity_multiplier": round(affinity_multiplier, 6),
            "proc_probability_per_event": round(probability_per_event, 8),
            "proc_probability_over_run": round(probability_over_run, 8),
            "standalone_contribution": round(standalone_contribution, 8),
            "contribution": round(standalone_contribution, 8),
        }
        factor_details.append(row)
        bucket = grouped.setdefault(
            skill_key,
            {
                "name": skill_name,
                "catalog_key": skill_key,
                "profile_weight": profile_weight,
                "failure_probability": 1.0,
                "factors": [],
            },
        )
        if source_type == "white_skill":
            bucket["name"] = skill_name
        bucket["failure_probability"] *= (1.0 - probability_per_event) ** event_count
        bucket["factors"].append(row)

    for member, position, role in members:
        affinity_value = max(0.0, float(affinities.get(role, 0.0)))
        for factor in _factor_list(member, "white_skill"):
            stars = int(factor.get("stars") or 0)
            name = str(factor.get("name") or "")
            key = slugify(name)
            register_source(
                role=role,
                position=position,
                skill_key=key,
                skill_name=name,
                source_type="white_skill",
                source_factor_name=name,
                stars=stars,
                base_rate=max(0.0, float(base_rates.get(str(stars), 0.0))),
                affinity_value=affinity_value,
            )

        for factor in _factor_list(member, "white_race"):
            stars = int(factor.get("stars") or 0)
            race_name = str(factor.get("name") or "")
            base_rate = max(0.0, float(race_base_rates.get(str(stars), 0.0)))
            for skill_key in granted_by_race.get(race_name, []):
                register_source(
                    role=role,
                    position=position,
                    skill_key=skill_key,
                    skill_name=skill_key,
                    source_type="white_race",
                    source_factor_name=race_name,
                    stars=stars,
                    base_rate=base_rate,
                    affinity_value=affinity_value,
                )

    raw = 0.0
    probability_raw = 0.0
    skill_details: list[dict[str, Any]] = []
    for bucket in grouped.values():
        probability_at_least_once = 1.0 - float(bucket["failure_probability"])
        probability_utility = max(
            0.0,
            float(_piecewise_score(probability_at_least_once, distinct_skill_curve)),
        )
        profile_weight = float(bucket["profile_weight"])
        probability_contribution = profile_weight * probability_at_least_once
        contribution = profile_weight * probability_utility
        probability_raw += probability_contribution
        raw += contribution
        carriers = list(bucket["factors"])
        skill_details.append(
            {
                "name": bucket["name"],
                "catalog_key": bucket["catalog_key"],
                "profile_weight": round(profile_weight, 6),
                "probability_at_least_once": round(probability_at_least_once, 8),
                "probability_utility": round(probability_utility, 8),
                "probability_contribution": round(probability_contribution, 8),
                "contribution": round(contribution, 8),
                "carrier_count": len(carriers),
                "roles": [str(item["role"]) for item in carriers],
                "source_types": sorted({str(item["source_type"]) for item in carriers}),
                "factors": carriers,
            }
        )

    scale = float((config.get("white_saturation") or {}).get(saturation_key, 1.0))
    skill_details.sort(key=lambda item: item["contribution"], reverse=True)
    factor_details.sort(key=lambda item: item["standalone_contribution"], reverse=True)
    return _saturating_score(raw, scale), {
        "raw": raw,
        "probability_raw": probability_raw,
        "scale": scale,
        "formula": "combine direct white and granted Race-Spark sources per distinct skill using their own base rates, individual affinity and Inspiration events; convert P through the distinct-skill utility curve; sum and saturate",
        "base_proc_rates": base_rates,
        "race_base_proc_rates": race_base_rates,
        "inspiration_event_count": event_count,
        "distinct_skill_probability_curve": distinct_skill_curve,
        "uses_individual_affinity": True,
        "race_skill_policy": "no arbitrary multiplier: Race Sparks use their lower 1/2/3% base rates and merge with direct white copies of the same granted skill",
        "diversity_policy": "very low chances are suppressed; useful distinct skills receive separate utility; repeated copies only increase the same skill probability with diminishing returns",
        "top_skills": skill_details[:20],
        "top_factors": factor_details[:30],
        "skill_count": len(skill_details),
        "factor_count": len(factor_details),
    }


def _race_scenario_score(
    members: list[tuple[dict[str, Any], str, str]],
    weight_lookup: Callable[[str], float],
    race_skill_map: dict[str, list[str]],
    config: dict[str, Any],
    saturation_key: str,
) -> tuple[float, dict[str, Any]]:
    """Score only the stat/scenario side of Race and Scenario Sparks.

    Skills granted by Race Sparks are scored in :func:`_white_score` with their
    actual 1/2/3% inheritance rates, preventing both an arbitrary multiplier and
    double counting in this component.
    """
    position_weights = config.get("position_transmission") or {}
    star_quality = config.get("star_quality") or {}
    race_config = config.get("race_factor") or {}
    base_per_star = float(race_config.get("base_per_star_quality", 0.06))
    scenario_per_star = float(race_config.get("scenario_per_star_quality", 0.10))
    raw = 0.0
    details: list[dict[str, Any]] = []
    for member, position, role in members:
        position_weight = float(position_weights.get(position, 1.0))
        for factor_type in ("white_race", "scenario"):
            for factor in _factor_list(member, factor_type):
                stars = int(factor.get("stars") or 0)
                name = str(factor.get("name") or "")
                star_weight = float(star_quality.get(str(stars), 0.0))
                if factor_type == "scenario":
                    base = scenario_per_star * star_weight
                    granted = []
                else:
                    base = base_per_star * star_weight
                    granted = race_skill_map.get(name, [])
                contribution = base * position_weight
                raw += contribution
                details.append(
                    {
                        "role": role,
                        "type": factor_type,
                        "name": name,
                        "stars": stars,
                        "granted_skill_keys": granted,
                        "granted_skills_scored_in": "white_skill" if granted else None,
                        "contribution": round(contribution, 6),
                    }
                )
    scale = float((config.get("race_saturation") or {}).get(saturation_key, 1.0))
    details.sort(key=lambda item: item["contribution"], reverse=True)
    return _saturating_score(raw, scale), {
        "raw": raw,
        "scale": scale,
        "formula": "Race/Scenario Spark stat utility only; granted skills are probability-scored in white_skill",
        "top_factors": details[:20],
        "factor_count": len(details),
    }


def _unique_score(
    members: list[tuple[dict[str, Any], str, str]],
    config: dict[str, Any],
    saturation_key: str,
) -> tuple[float, dict[str, Any]]:
    position_weights = config.get("position_transmission") or {}
    star_quality = config.get("unique_star_quality") or {"1": 0.82, "2": 0.91, "3": 1.0}
    raw = 0.0
    slot_count = max(1, len(members))
    details: list[dict[str, Any]] = []
    for member, position, role in members:
        position_weight = float(position_weights.get(position, 1.0))
        factors = _factor_list(member, "unique")
        if not factors:
            details.append({"role": role, "name": None, "stars": 0, "star_quality": 0.0, "position_weight": position_weight, "contribution": 0.0})
            continue
        for factor in factors:
            stars = int(factor.get("stars") or 0)
            quality = float(star_quality.get(str(stars), 0.0))
            contribution = quality * position_weight
            raw += contribution
            details.append({
                "role": role,
                "name": factor.get("name"),
                "stars": stars,
                "star_quality": round(quality, 4),
                "position_weight": position_weight,
                "contribution": round(contribution, 6),
            })
    score = min(100.0, 100.0 * raw / slot_count)
    return score, {
        "raw": raw,
        "slot_count": slot_count,
        "formula": "100 × sum(unique star tier × parent/grandparent transmission position) / lineage slots",
        "star_tiers": star_quality,
        "factors": details,
    }


def _branch_affinity(
    resolver: AffinityResolver,
    ace_chara_id: int,
    veteran: dict[str, Any],
    g1_bonus_value: int,
) -> dict[str, Any]:
    parent_chara = int(veteran.get("chara_id") or 0)
    lineage = veteran.get("when_used_as_parent") or {}
    gp1 = lineage.get("grandparent_1")
    gp2 = lineage.get("grandparent_2")
    base_pair = resolver.pair(ace_chara_id, parent_chara)
    triple_1 = resolver.triple(ace_chara_id, parent_chara, int((gp1 or {}).get("chara_id") or 0)) if gp1 else 0
    triple_2 = resolver.triple(ace_chara_id, parent_chara, int((gp2 or {}).get("chara_id") or 0)) if gp2 else 0
    parent_g1 = _member_g1(veteran)
    common_1 = sorted(parent_g1 & _member_g1(gp1))
    common_2 = sorted(parent_g1 & _member_g1(gp2))
    g1_bonus = g1_bonus_value * (len(common_1) + len(common_2))
    return {
        "base": base_pair + triple_1 + triple_2,
        "g1_bonus": g1_bonus,
        "total": base_pair + triple_1 + triple_2 + g1_bonus,
        "details": {
            "ace_parent_pair": base_pair,
            "ace_parent_gp1_triple": triple_1,
            "ace_parent_gp2_triple": triple_2,
            "parent_gp1_common_g1": common_1,
            "parent_gp2_common_g1": common_2,
        },
    }




def _branch_inheritance_affinities(
    resolver: AffinityResolver,
    ace_chara_id: int,
    veteran: dict[str, Any],
    g1_bonus_value: int,
) -> dict[str, float]:
    """Partial inheritance coefficients for an isolated parent branch.

    The parent↔other-parent terms are unknown here and are added by the final
    pair evaluator. Grandparent coefficients are already exact for this branch.
    """
    parent_chara = int(veteran.get("chara_id") or 0)
    lineage = veteran.get("when_used_as_parent") or {}
    gp1 = lineage.get("grandparent_1")
    gp2 = lineage.get("grandparent_2")
    gp1_chara = int((gp1 or {}).get("chara_id") or 0)
    gp2_chara = int((gp2 or {}).get("chara_id") or 0)
    ace_parent = resolver.pair(ace_chara_id, parent_chara)
    triple_1 = resolver.triple(ace_chara_id, parent_chara, gp1_chara) if gp1 else 0
    triple_2 = resolver.triple(ace_chara_id, parent_chara, gp2_chara) if gp2 else 0
    parent_g1 = _member_g1(veteran)
    gp1_g1 = g1_bonus_value * len(parent_g1 & _member_g1(gp1))
    gp2_g1 = g1_bonus_value * len(parent_g1 & _member_g1(gp2))
    return {
        "parent": float(ace_parent + triple_1 + triple_2 + gp1_g1 + gp2_g1),
        "grandparent_1": float(triple_1 + gp1_g1),
        "grandparent_2": float(triple_2 + gp2_g1),
    }


def _pair_inheritance_affinities(
    resolver: AffinityResolver,
    ace_chara_id: int,
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    g1_bonus_value: int,
) -> dict[str, Any]:
    """Compute the six modern individual inheritance coefficients.

    These are the coefficients used by Spark proc estimates, not six disjoint
    shares of the in-game overall ◎/〇/△ total. Shared links intentionally occur
    in both the parent and the corresponding grandparent coefficient.
    """
    p1_chara = int(parent_1.get("chara_id") or 0)
    p2_chara = int(parent_2.get("chara_id") or 0)
    p1_lineage = parent_1.get("when_used_as_parent") or {}
    p2_lineage = parent_2.get("when_used_as_parent") or {}
    p1_gp1 = p1_lineage.get("grandparent_1")
    p1_gp2 = p1_lineage.get("grandparent_2")
    p2_gp1 = p2_lineage.get("grandparent_1")
    p2_gp2 = p2_lineage.get("grandparent_2")

    p1_gp1_triple = resolver.triple(ace_chara_id, p1_chara, int((p1_gp1 or {}).get("chara_id") or 0)) if p1_gp1 else 0
    p1_gp2_triple = resolver.triple(ace_chara_id, p1_chara, int((p1_gp2 or {}).get("chara_id") or 0)) if p1_gp2 else 0
    p2_gp1_triple = resolver.triple(ace_chara_id, p2_chara, int((p2_gp1 or {}).get("chara_id") or 0)) if p2_gp1 else 0
    p2_gp2_triple = resolver.triple(ace_chara_id, p2_chara, int((p2_gp2 or {}).get("chara_id") or 0)) if p2_gp2 else 0

    parent_pair_base = resolver.pair(p1_chara, p2_chara)
    p1_g1 = _member_g1(parent_1)
    p2_g1 = _member_g1(parent_2)
    p1_p2_g1 = g1_bonus_value * len(p1_g1 & p2_g1)
    p1_gp1_g1 = g1_bonus_value * len(p1_g1 & _member_g1(p1_gp1))
    p1_gp2_g1 = g1_bonus_value * len(p1_g1 & _member_g1(p1_gp2))
    p2_gp1_g1 = g1_bonus_value * len(p2_g1 & _member_g1(p2_gp1))
    p2_gp2_g1 = g1_bonus_value * len(p2_g1 & _member_g1(p2_gp2))

    ace_p1 = resolver.pair(ace_chara_id, p1_chara)
    ace_p2 = resolver.pair(ace_chara_id, p2_chara)
    values = {
        "parent_1": float(ace_p1 + parent_pair_base + p1_gp1_triple + p1_gp2_triple + p1_p2_g1 + p1_gp1_g1 + p1_gp2_g1),
        "parent_1_grandparent_1": float(p1_gp1_triple + p1_gp1_g1),
        "parent_1_grandparent_2": float(p1_gp2_triple + p1_gp2_g1),
        "parent_2": float(ace_p2 + parent_pair_base + p2_gp1_triple + p2_gp2_triple + p1_p2_g1 + p2_gp1_g1 + p2_gp2_g1),
        "parent_2_grandparent_1": float(p2_gp1_triple + p2_gp1_g1),
        "parent_2_grandparent_2": float(p2_gp2_triple + p2_gp2_g1),
    }
    return {
        "values": values,
        "formula": {
            "parent": "pair(Ace,parent) + pair(parent1,parent2) + two Ace-parent-GP triples + three modern G1 links",
            "grandparent": "triple(Ace,parent,grandparent) + 3 × shared G1(parent,grandparent)",
        },
        "assumptions": {
            "affinity_system": "modern_g1",
            "g1_only": True,
            "g1_bonus_per_overlap": g1_bonus_value,
            "parent_parent_link_included": True,
            "g2_g3_and_titles_excluded": True,
        },
    }

def evaluate_parent_branch(
    resolver: AffinityResolver,
    ace: dict[str, Any],
    veteran: dict[str, Any],
    *,
    surface: str,
    distance: str,
    style: str,
    weight_lookup: Callable[[str], float],
    race_skills: dict[str, list[str]],
    config: dict[str, Any],
    g1_bonus_value: int | None = None,
    affinity_thresholds: Iterable[Iterable[float]] | None = None,
) -> dict[str, Any]:
    """Evaluate one complete parent branch with the canonical local scorer.

    A branch is the final parent plus its two visible grandparents. Keeping this
    logic public lets online candidates use exactly the same formula as local
    veterans instead of maintaining a second, subtly different implementation.
    """
    ace_chara = int(ace.get("chara_id") or 0)
    if ace_chara <= 0:
        raise OptimizerError("Ace invalide pour l'évaluation de branche parent.")
    parent_chara = int(veteran.get("chara_id") or 0)
    if parent_chara <= 0:
        raise OptimizerError("Parent invalide pour l'évaluation de branche.")
    if parent_chara == ace_chara:
        raise OptimizerError("L'Ace ne peut pas être utilisé comme son propre parent.")

    affinity_cfg = config.get("affinity") or {}
    resolved_g1_bonus = int(
        affinity_cfg.get("g1_common_bonus", 3)
        if g1_bonus_value is None
        else g1_bonus_value
    )
    thresholds = affinity_thresholds or affinity_cfg.get("parent_branch_thresholds") or [[0, 0], [95, 100]]
    weights = _mode_weights(config, "parent_branch")
    members = _lineage_members(veteran)
    affinity = _branch_affinity(resolver, ace_chara, veteran, resolved_g1_bonus)
    inheritance_affinities = _branch_inheritance_affinities(
        resolver, ace_chara, veteran, resolved_g1_bonus
    )
    blue, blue_detail = _blue_score(members, distance, config)
    pink, pink_detail = _pink_score(
        members, ace, surface, distance, style, config, mode="parent_branch",
        inheritance_affinities=inheritance_affinities,
    )
    white, white_detail = _white_score(
        members, weight_lookup, config, "parent_branch",
        inheritance_affinities=inheritance_affinities,
        race_skill_map=race_skills,
    )
    race, race_detail = _race_scenario_score(members, weight_lookup, race_skills, config, "parent_branch")
    unique, unique_detail = _unique_score(members, config, "parent_branch")
    components = {
        "blue": blue,
        "pink": pink,
        "distance_s": float(pink_detail["distance_s"]["score"]),
        "pink_other": float(pink_detail["pink_other"]["score"]),
        "white_skill": white,
        "race_scenario": race,
        "unique": unique,
    }
    affinity_score = _affinity_score(affinity["total"], thresholds)
    components["affinity"] = affinity_score
    branch_viability = _distance_viability(
        mode="parent_branch",
        distance_detail=pink_detail["distance_s"],
        white_score=white,
        blue_score=blue,
        config=config,
    )
    pink_detail["distance_s"]["viability"] = branch_viability
    component_details = {
        "blue": blue_detail,
        "pink": pink_detail,
        "white_skill": white_detail,
        "race_scenario": race_detail,
        "unique": unique_detail,
        "affinity": {
            "raw_total": affinity["total"],
            "base": affinity["base"],
            "g1_bonus": affinity["g1_bonus"],
            "thresholds": thresholds,
            "score": affinity_score,
            "inheritance_affinities_partial": inheritance_affinities,
            "note": "Branch-only proc coefficients exclude the unknown other-parent link; final pair evaluation recomputes exact values.",
        },
    }
    return {
        **_candidate_identity(veteran),
        "veteran": veteran,
        "affinity": affinity,
        "components": components,
        "component_details": component_details,
        "score": _weighted_total(components, weights),
        "score_breakdown": _score_breakdown(components, weights),
        "distance_viability": branch_viability,
        "distance_s_summary": pink_detail["distance_s"],
    }


def evaluate_parent_pair(
    resolver: AffinityResolver,
    ace: dict[str, Any],
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    *,
    surface: str,
    distance: str,
    style: str,
    weight_lookup: Callable[[str], float],
    race_skills: dict[str, list[str]],
    config: dict[str, Any],
    parent_1_branch: dict[str, Any] | None = None,
    parent_2_branch: dict[str, Any] | None = None,
    g1_bonus_value: int | None = None,
    affinity_thresholds: Iterable[Iterable[float]] | None = None,
) -> dict[str, Any]:
    """Evaluate a final Ace parent pair through the canonical six-member engine.

    The exact affinity includes both Ace↔parent branches, their four parent↔GP
    links and the parent↔parent link. Factors are scored over the six visible
    lineage members. This is the same engine used by the local optimizer and by
    the uma.moe parent search.
    """
    chara_1 = int(parent_1.get("chara_id") or 0)
    chara_2 = int(parent_2.get("chara_id") or 0)
    if chara_1 <= 0 or chara_2 <= 0:
        raise OptimizerError("Paire de parents invalide : personnage non résolu.")
    if chara_1 == chara_2:
        raise OptimizerError("Les deux parents doivent être deux personnages différents.")

    affinity_cfg = config.get("affinity") or {}
    resolved_g1_bonus = int(
        affinity_cfg.get("g1_common_bonus", 3)
        if g1_bonus_value is None
        else g1_bonus_value
    )
    thresholds = affinity_thresholds or affinity_cfg.get("parent_pair_thresholds") or [[0, 0], [151, 100]]
    weights = _mode_weights(config, "parent_pair")

    left = parent_1_branch or evaluate_parent_branch(
        resolver, ace, parent_1, surface=surface, distance=distance, style=style,
        weight_lookup=weight_lookup, race_skills=race_skills, config=config,
        g1_bonus_value=resolved_g1_bonus,
    )
    right = parent_2_branch or evaluate_parent_branch(
        resolver, ace, parent_2, surface=surface, distance=distance, style=style,
        weight_lookup=weight_lookup, race_skills=race_skills, config=config,
        g1_bonus_value=resolved_g1_bonus,
    )

    parent_pair_base = resolver.pair(chara_1, chara_2)
    parent_common = sorted(_member_g1(parent_1) & _member_g1(parent_2))
    parent_pair_g1 = resolved_g1_bonus * len(parent_common)
    inheritance_affinity_detail = _pair_inheritance_affinities(
        resolver, int(ace.get("chara_id") or 0), parent_1, parent_2, resolved_g1_bonus
    )
    affinity = {
        "base": int(left["affinity"]["base"]) + int(right["affinity"]["base"]) + parent_pair_base,
        "g1_bonus": int(left["affinity"]["g1_bonus"]) + int(right["affinity"]["g1_bonus"]) + parent_pair_g1,
        "total": int(left["affinity"]["total"]) + int(right["affinity"]["total"]) + parent_pair_base + parent_pair_g1,
        "parent_parent_base": parent_pair_base,
        "parent_parent_common_g1": parent_common,
        "parent_parent_common_g1_bonus": parent_pair_g1,
        "parent_1_branch": left["affinity"],
        "parent_2_branch": right["affinity"],
        "inheritance_affinities": inheritance_affinity_detail,
        "formula": (
            "branch(Ace,parent1,GP1,GP2) + branch(Ace,parent2,GP3,GP4) "
            "+ pair(parent1,parent2), with the five visible modern G1 links"
        ),
    }

    members = _lineage_members(parent_1, "parent_1") + _lineage_members(parent_2, "parent_2")
    blue, blue_detail = _blue_score(members, distance, config)
    pink, pink_detail = _pink_score(
        members, ace, surface, distance, style, config, mode="parent_pair",
        inheritance_affinities=inheritance_affinity_detail["values"],
    )
    white, white_detail = _white_score(
        members, weight_lookup, config, "parent_pair",
        inheritance_affinities=inheritance_affinity_detail["values"],
        race_skill_map=race_skills,
    )
    race, race_detail = _race_scenario_score(members, weight_lookup, race_skills, config, "parent_pair")
    unique, unique_detail = _unique_score(members, config, "parent_pair")
    components = {
        "blue": blue,
        "pink": pink,
        "distance_s": float(pink_detail["distance_s"]["score"]),
        "pink_other": float(pink_detail["pink_other"]["score"]),
        "white_skill": white,
        "race_scenario": race,
        "unique": unique,
    }
    affinity_score = _affinity_score(affinity["total"], thresholds)
    components["affinity"] = affinity_score
    pair_viability = _distance_viability(
        mode="parent_pair",
        distance_detail=pink_detail["distance_s"],
        white_score=white,
        # Compensation asks whether the blue lineage is intrinsically
        # excellent. Use the uncompressed quality here; the distance-specific
        # influence only controls how strongly blues affect normal ranking.
        blue_score=float(blue_detail.get("uncompressed_score", blue)),
        config=config,
    )
    pink_detail["distance_s"]["viability"] = pair_viability
    component_details = {
        "blue": blue_detail,
        "pink": pink_detail,
        "white_skill": white_detail,
        "race_scenario": race_detail,
        "unique": unique_detail,
        "affinity": {
            "raw_total": affinity["total"],
            "base": affinity["base"],
            "g1_bonus": affinity["g1_bonus"],
            "thresholds": thresholds,
            "score": affinity_score,
            "links": {
                "parent_1_branch": left["affinity"],
                "parent_2_branch": right["affinity"],
                "parent_parent_base": parent_pair_base,
                "parent_parent_common_g1": parent_common,
                "parent_parent_common_g1_bonus": parent_pair_g1,
            },
            "inheritance_affinities": inheritance_affinity_detail,
            "note": "Overall compatibility remains diagnostic; Spark proc estimates use the six individual coefficients.",
        },
    }
    return {
        "parent_1": _candidate_identity(parent_1),
        "parent_2": _candidate_identity(parent_2),
        "affinity": affinity,
        "components": components,
        "component_details": component_details,
        "score": _weighted_total(components, weights),
        "score_breakdown": _score_breakdown(components, weights),
        "distance_viability": pair_viability,
        "distance_s_summary": pink_detail["distance_s"],
        "aptitude_summaries": pink_detail["dimensions"],
    }


def parent_pair_sort_key(row: dict[str, Any]) -> tuple[float, float, float, float, float]:
    """Prioritize viability, then the configurable weighted quality score.

    Distance-S probability is already converted through a saturating utility
    curve inside the distance component. Keeping raw P(S) ahead of the global
    score would make small differences near the practical ceiling dominate
    much better white/blue lineages.
    """
    viability = row.get("distance_viability") or {}
    pink_detail = ((row.get("component_details") or {}).get("pink") or {})
    distance_detail = row.get("distance_s_summary") or pink_detail.get("distance_s") or {}
    return (
        float(viability.get("sort_priority") or 0),
        float(row.get("score") or 0),
        float((row.get("components") or {}).get("white_skill") or 0),
        float((row.get("components") or {}).get("blue") or 0),
        float(distance_detail.get("probability_reach_s") or 0),
    )


def _candidate_identity(veteran: dict[str, Any]) -> dict[str, Any]:
    lineage = veteran.get("when_used_as_parent") or {}
    return {
        "trained_chara_id": veteran.get("trained_chara_id"),
        "card_id": veteran.get("card_id"),
        "chara_id": veteran.get("chara_id"),
        "uma_name": veteran.get("uma_name"),
        "card_name": veteran.get("card_name"),
        "rank": veteran.get("rank"),
        "rank_score": veteran.get("rank_score"),
        "stats": veteran.get("stats") or {},
        "grandparent_1": (lineage.get("grandparent_1") or {}).get("card_name"),
        "grandparent_2": (lineage.get("grandparent_2") or {}).get("card_name"),
    }


def _affinity_score(raw: float, thresholds: Iterable[Iterable[float]]) -> float:
    return max(0.0, min(100.0, _piecewise_score(raw, thresholds)))


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def optimize_parents(
    master_path: str | Path,
    linked_veterans_path: str | Path,
    simulator_weights_path: str | Path,
    race_factor_catalog_path: str | Path,
    skill_catalog_path: str | Path,
    output_dir: str | Path,
    *,
    ace_card_id: int,
    future_parent_card_id: int | None = None,
    surface: str,
    distance: str,
    style: str,
    course_weights_path: str | Path | None = None,
    course_key: str | None = None,
    course_conditions: dict[str, int | list[int] | tuple[int, ...] | set[int] | None] | None = None,
    scoring_config_path: str | Path | None = None,
    top_n: int = 30,
    logger: Callable[[str], None] | None = None,
) -> OptimizerResult:
    log = logger or _logger_default
    if surface not in SURFACES or distance not in DISTANCES or style not in STYLES:
        raise OptimizerError(f"Profil invalide : {surface}/{distance}/{style}")
    top_n = max(1, min(int(top_n), 500))

    master = Path(master_path).expanduser().resolve()
    linked_path = Path(linked_veterans_path).expanduser().resolve()
    weights_path = Path(simulator_weights_path).expanduser().resolve()
    race_catalog_path = Path(race_factor_catalog_path).expanduser().resolve()
    skill_catalog_path_resolved = Path(skill_catalog_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    course_path = Path(course_weights_path).expanduser().resolve() if course_weights_path else None
    config_path = Path(scoring_config_path).expanduser().resolve() if scoring_config_path else Path(__file__).resolve().parent / "default_parent_scoring.json"

    for required in (master, linked_path, weights_path, race_catalog_path, skill_catalog_path_resolved, config_path):
        if not required.is_file():
            raise OptimizerError(f"Fichier requis introuvable : {required}")
    if course_key and (course_path is None or not course_path.is_file()):
        raise OptimizerError("Un preset de course a été choisi, mais course_skill_weights.json est introuvable.")

    destination.mkdir(parents=True, exist_ok=True)
    log("Chargement des vétérans enrichis et des poids skills…")
    linked_payload = _read_json(linked_path)
    weights_payload = _read_json(weights_path)
    race_catalog = _read_json(race_catalog_path)
    skill_catalog = _read_json(skill_catalog_path_resolved)
    config = _read_json(config_path)
    course_payload = _read_json(course_path) if course_path and course_path.is_file() else None
    veterans = list(linked_payload.get("veterans") or [])
    if not veterans:
        raise OptimizerError("Aucun vétéran dans veterans_legacy_linked.json")

    resolver = AffinityResolver(master)
    try:
        ace = resolver.ace_details(int(ace_card_id), surface, distance, style)
        ace_chara = int(ace["chara_id"])
        future_parent = (
            resolver.card_details(int(future_parent_card_id))
            if future_parent_card_id is not None
            else None
        )
        if future_parent is not None and int(future_parent["chara_id"]) == ace_chara:
            raise OptimizerError("L'Ace et le parent à produire doivent être deux personnages différents.")
        normalized_conditions: dict[str, set[int]] = {}
        for key, raw_value in (course_conditions or {}).items():
            if raw_value is None or raw_value == "":
                continue
            if isinstance(raw_value, (list, tuple, set)):
                values = {int(value) for value in raw_value}
            else:
                values = {int(raw_value)}
            if values:
                normalized_conditions[str(key)] = values
        if course_key and course_payload:
            selected_course = (course_payload.get("courses") or {}).get(course_key) or {}
            # A course key is sufficient on its own: static green conditions
            # bundled with the preset are applied unless explicitly overridden
            # by GUI/CLI inputs.
            for key, raw_value in (selected_course.get("conditions") or {}).items():
                if str(key) in normalized_conditions or raw_value is None or raw_value == "":
                    continue
                if isinstance(raw_value, (list, tuple, set)):
                    values = {int(value) for value in raw_value}
                else:
                    values = {int(raw_value)}
                if values:
                    normalized_conditions[str(key)] = values
            if "track_id" not in normalized_conditions:
                racecourse = str(((selected_course.get("race") or {}).get("racecourse")) or "").strip().lower()
                if racecourse and racecourse not in {"variable", "unknown racetrack"}:
                    for track_name, track_id in resolver.track_name_to_id.items():
                        if track_name == racecourse or track_name.startswith(racecourse) or racecourse.startswith(track_name):
                            normalized_conditions["track_id"] = {int(track_id)}
                            break
        course_condition_config = config.get("course_conditions") or {}
        active_green_floor = float(course_condition_config.get("active_green_floor", 0.12))
        green_floors = {
            str(key): float(value)
            for key, value in (course_condition_config.get("floors") or {}).items()
        }
        green_modes = {
            str(key): str(value)
            for key, value in (course_condition_config.get("modes") or {}).items()
        }
        weight_lookup, weight_source, condition_diagnostics = _selected_weight_lookup(
            weights_payload, course_payload, skill_catalog, surface, distance, style,
            course_key, normalized_conditions, active_green_floor, green_floors, green_modes
        )
        race_skills = _race_skill_map(race_catalog)
        valid_veterans = [
            veteran
            for veteran in veterans
            if int(veteran.get("chara_id") or 0) != ace_chara
        ]
        if not valid_veterans:
            raise OptimizerError("Aucun vétéran compatible après exclusion de l'Ace lui-même.")

        affinity_config = config.get("affinity") or {}
        g1_bonus_value = int(affinity_config.get("g1_common_bonus", 3))
        branch_affinity_thresholds = affinity_config.get("parent_branch_thresholds") or [[0, 0], [95, 100]]
        pair_affinity_thresholds = affinity_config.get("parent_pair_thresholds") or [[0, 0], [151, 100]]
        future_affinity_thresholds = affinity_config.get("future_branch_base_thresholds") or [[0, 0], [48, 100]]
        future_g1_thresholds = affinity_config.get("future_g1_thresholds") or [[0, 0], [20, 100]]
        branch_rows: list[dict[str, Any]] = []
        log(f"Évaluation de {len(valid_veterans)} lignées candidates…")
        for index, veteran in enumerate(valid_veterans, 1):
            branch_rows.append(
                evaluate_parent_branch(
                    resolver,
                    ace,
                    veteran,
                    surface=surface,
                    distance=distance,
                    style=style,
                    weight_lookup=weight_lookup,
                    race_skills=race_skills,
                    config=config,
                    g1_bonus_value=g1_bonus_value,
                    affinity_thresholds=branch_affinity_thresholds,
                )
            )
            if index % 50 == 0 or index == len(valid_veterans):
                log(f"Lignées : {index}/{len(valid_veterans)}")

        branch_p95 = _quantile((row["affinity"]["total"] for row in branch_rows), 0.95)
        branch_rows.sort(key=lambda row: (row["score"], row["affinity"]["total"]), reverse=True)

        log("Recherche des meilleures paires de parents…")
        pair_rows: list[dict[str, Any]] = []
        # Full search is cheap for the current 259-veteran export (~33k pairs).
        for left_index, left in enumerate(branch_rows):
            v1 = left["veteran"]
            for right in branch_rows[left_index + 1 :]:
                v2 = right["veteran"]
                if int(v1.get("chara_id") or 0) == int(v2.get("chara_id") or 0):
                    continue
                pair_rows.append(
                    evaluate_parent_pair(
                        resolver,
                        ace,
                        v1,
                        v2,
                        surface=surface,
                        distance=distance,
                        style=style,
                        weight_lookup=weight_lookup,
                        race_skills=race_skills,
                        config=config,
                        parent_1_branch=left,
                        parent_2_branch=right,
                        g1_bonus_value=g1_bonus_value,
                        affinity_thresholds=pair_affinity_thresholds,
                    )
                )

        pair_p95 = _quantile((row["affinity"]["total"] for row in pair_rows), 0.95)
        pair_rows.sort(key=parent_pair_sort_key, reverse=True)

        log("Évaluation des futurs grands-parents…")
        future_rows: list[dict[str, Any]] = []
        future_parent_chara = int(future_parent["chara_id"]) if future_parent else None
        future_candidates = [
            veteran
            for veteran in veterans
            if future_parent_chara is None
            or int(veteran.get("chara_id") or 0) != future_parent_chara
        ]
        future_branch_base = (
            resolver.pair(ace_chara, future_parent_chara)
            if future_parent_chara is not None
            else None
        )
        for veteran in future_candidates:
            members = [(veteran, "grandparent", "candidate")]
            candidate_chara = int(veteran.get("chara_id") or 0)
            if future_parent_chara is not None:
                affinity_raw = resolver.triple(ace_chara, future_parent_chara, candidate_chara)
                affinity_mode = "exact_triple_ace_parent_grandparent"
            else:
                affinity_raw = resolver.pair(ace_chara, candidate_chara)
                affinity_mode = "ace_candidate_pair_fallback"
            g1_count = len(_member_g1(veteran))
            blue, blue_detail = _blue_score(members, distance, config)
            pink, pink_detail = _future_grandparent_pink_score(
                members, ace, surface, distance, style, config
            )
            white, white_detail = _future_grandparent_white_score(
                members, weight_lookup, config, race_skills
            )
            production_lineage = _lineage_members(veteran)
            white_generation, white_generation_detail = _white_generation_support_score(
                production_lineage, weight_lookup, config
            )
            unique, unique_detail = _unique_score(members, config, "future_grandparent")
            future_rows.append(
                {
                    **_candidate_identity(veteran),
                    "affinity_raw": affinity_raw,
                    "affinity_mode": affinity_mode,
                    "future_parent_base_affinity": future_branch_base,
                    "future_branch_base_total": (future_branch_base + affinity_raw if future_branch_base is not None else affinity_raw),
                    "g1_count": g1_count,
                    "components": {
                        "blue": blue,
                        "pink": pink,
                        "white_skill": white,
                        "white_generation": white_generation,
                        "unique": unique,
                    },
                    "component_details": {
                        "blue": blue_detail,
                        "pink": {
                            **pink_detail,
                            "evaluation_context": "future_grandparent_simple_quality",
                        },
                        "white_skill": {
                            **white_detail,
                            "evaluation_context": "future_grandparent_direct_factor_quality",
                        },
                        "white_generation": {
                            **white_generation_detail,
                            "evaluation_context": "intermediate_run_that_creates_target_parent",
                        },
                        "unique": unique_detail,
                    },
                }
            )
        future_affinity_p95 = _quantile((row["affinity_raw"] for row in future_rows), 0.95)
        future_g1_p95 = max(1.0, _quantile((row["g1_count"] for row in future_rows), 0.95))
        future_weights = _mode_weights(config, "future_grandparent")
        for row in future_rows:
            affinity_basis = float(row.get("future_branch_base_total") or row["affinity_raw"])
            affinity_score = _affinity_score(affinity_basis, future_affinity_thresholds)
            g1_score = _affinity_score(float(row["g1_count"]), future_g1_thresholds)
            row["components"]["affinity"] = affinity_score
            row["components"]["g1_potential"] = g1_score
            row["component_details"]["affinity"] = {
                "pair_ace_target_parent": row.get("future_parent_base_affinity"),
                "candidate_triple_contribution": row["affinity_raw"],
                "branch_base_total": affinity_basis,
                "same_as_ace": int(row.get("chara_id") or 0) == ace_chara,
                "thresholds": future_affinity_thresholds,
                "score": affinity_score,
            }
            row["component_details"]["g1_potential"] = {
                "different_g1_count": row["g1_count"],
                "thresholds": future_g1_thresholds,
                "score": g1_score,
                "note": "Potential only: future bonus depends on which of these G1 the new parent also wins.",
            }
            row["score"] = _weighted_total(row["components"], future_weights)
            row["score_breakdown"] = _score_breakdown(row["components"], future_weights)
        future_rows.sort(key=lambda row: (row["score"], row["g1_count"]), reverse=True)

        # Remove the embedded source veteran before serialization.
        serializable_branches = []
        for row in branch_rows[:top_n]:
            copy = {key: value for key, value in row.items() if key != "veteran"}
            serializable_branches.append(copy)
        serializable_pairs = pair_rows[:top_n]
        serializable_future = future_rows[:top_n]

        generated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "metadata": {
                "schema_version": 6,
                "generated_at_utc": generated_at,
                "purpose": "Rank final parent pairs, parent branches and future grandparents for a target Ace profile.",
                "source_master": {"filename": master.name, "sha256": _sha256(master)},
                "source_veterans": {"filename": linked_path.name, "sha256": _sha256(linked_path)},
                "source_skill_weights": {"filename": weights_path.name, "sha256": _sha256(weights_path)},
                "source_race_factor_catalog": {"filename": race_catalog_path.name, "sha256": _sha256(race_catalog_path)},
                "source_skill_catalog": {"filename": skill_catalog_path_resolved.name, "sha256": _sha256(skill_catalog_path_resolved)},
                "source_course_weights": ({"filename": course_path.name, "sha256": _sha256(course_path)} if course_path and course_path.is_file() else None),
                "source_scoring_config": {"filename": config_path.name, "sha256": _sha256(config_path)},
                "candidate_count": len(valid_veterans),
                "pair_count": len(pair_rows),
                "top_n": top_n,
                "notes": [
                    "Final-parent affinity is exact for each complete pair, including both parent branches, parent-parent base compatibility and common G1 bonuses.",
                    (
                        "Future-grandparent affinity uses the exact triple(Ace, target parent, candidate) contribution."
                        if future_parent is not None
                        else "Future-grandparent affinity uses pair(Ace, candidate) as a fallback because no target parent was selected."
                    ),
                    "Parent branches and final pairs use the probability-aware pink/white model with individual affinities. Future-grandparent factors deliberately use the simpler pre-session quality model: no proc percentage, initial aptitude or P(S) is calculated.",
                    "For future-grandparent production, matching white skill Sparks on the candidate and its two current parents add only their incremental lineage-copy bonus; learned gold/basic form and base generation chance are ignored. Race/scenario Sparks are excluded.",
                    "A trainee repeated as her own grandparent contributes zero base compatibility; a raw MDB group intersection must not be used for duplicate characters.",
                    "Blue and compatibility components are threshold-oriented and saturate; 2-star blue is acceptable, while 3-star is an incremental improvement rather than a requirement.",
                    "Distance-S support is scored separately from surface/style pinks only for parent branches and final pairs. Final pairs are ordered by Distance-S viability before their additive score.",
                    "Parent branches are classified as deficit/light/balanced/distance carrier, but are not hard-gated because two branches may complement each other.",
                    "Race Sparks have a low base value and only gain meaningful value when they grant a relevant course-static skill; the direct white skill remains substantially more valuable.",
                ],
            },
            "ace": ace,
            "future_parent": future_parent,
            "profile": {
                "surface": surface,
                "distance": distance,
                "style": style,
                "course_key": course_key,
                "weight_source": weight_source,
                "course_conditions": {key: sorted(values) for key, values in normalized_conditions.items()},
                "course_condition_weight_diagnostics": condition_diagnostics,
                "active_green_floor": active_green_floor,
                "course_green_floors": green_floors,
                "course_green_modes": green_modes,
            },
            "normalization": {
                "branch_affinity_p95": branch_p95,
                "pair_affinity_p95": pair_p95,
                "future_affinity_p95": future_affinity_p95,
                "future_g1_count_p95": future_g1_p95,
            },
            "scoring_weights": config.get("mode_weights"),
            "scoring_thresholds": {
                "parent_branch_affinity": branch_affinity_thresholds,
                "parent_pair_affinity": pair_affinity_thresholds,
                "future_branch_base_affinity": future_affinity_thresholds,
                "future_g1_potential": future_g1_thresholds,
            },
            "top_parent_candidates": serializable_branches,
            "top_parent_pairs": serializable_pairs,
            "top_future_grandparents": serializable_future,
        }

        rankings_json = destination / "legacy_parent_rankings.json"
        parent_candidates_csv = destination / "legacy_parent_candidates.csv"
        parent_pairs_csv = destination / "legacy_parent_pairs.csv"
        future_csv = destination / "legacy_future_grandparents.csv"
        _write_json(rankings_json, payload)

        candidate_csv_rows = [
            {
                "rank": rank,
                "score": round(row["score"], 4),
                "trained_chara_id": row["trained_chara_id"],
                "rank_score": row.get("rank_score"),
                "parent": row["card_name"],
                "grandparent_1": row["grandparent_1"],
                "grandparent_2": row["grandparent_2"],
                "affinity_total": row["affinity"]["total"],
                "affinity_base": row["affinity"]["base"],
                "affinity_g1_bonus": row["affinity"]["g1_bonus"],
                "affinity_component_score": round(row["components"]["affinity"], 3),
                "distance_status": row["distance_viability"]["key"],
                "distance_tier": row["distance_viability"]["tier"],
                "distance_stars": row["distance_s_summary"]["total_stars"],
                "distance_carriers": row["distance_s_summary"]["carrier_count"],
                "distance_support": row["distance_s_summary"]["weighted_support"],
                "distance_initial_rank": row["distance_s_summary"]["initial_rank_label"],
                "distance_probability_a": round(100.0 * row["distance_s_summary"]["probability_reach_a"], 3),
                "distance_probability_s": round(100.0 * row["distance_s_summary"]["probability_reach_s"], 3),
                "blue": round(row["components"]["blue"], 3),
                "distance_s": round(row["components"]["distance_s"], 3),
                "pink_other": round(row["components"]["pink_other"], 3),
                "pink": round(row["components"]["pink"], 3),
                "white_skill": round(row["components"]["white_skill"], 3),
                "race_scenario": round(row["components"]["race_scenario"], 3),
                "unique": round(row["components"]["unique"], 3),
            }
            for rank, row in enumerate(branch_rows, 1)
        ]
        _write_csv(
            parent_candidates_csv,
            candidate_csv_rows,
            ["rank", "score", "trained_chara_id", "rank_score", "parent", "grandparent_1", "grandparent_2", "affinity_total", "affinity_base", "affinity_g1_bonus", "affinity_component_score", "distance_status", "distance_tier", "distance_stars", "distance_carriers", "distance_support", "distance_initial_rank", "distance_probability_a", "distance_probability_s", "blue", "distance_s", "pink_other", "pink", "white_skill", "race_scenario", "unique"],
        )

        pair_csv_rows = [
            {
                "rank": rank,
                "score": round(row["score"], 4),
                "parent_1_id": row["parent_1"]["trained_chara_id"],
                "parent_1_rank_score": row["parent_1"].get("rank_score"),
                "parent_1": row["parent_1"]["card_name"],
                "parent_2_id": row["parent_2"]["trained_chara_id"],
                "parent_2_rank_score": row["parent_2"].get("rank_score"),
                "parent_2": row["parent_2"]["card_name"],
                "affinity_total": row["affinity"]["total"],
                "affinity_base": row["affinity"]["base"],
                "affinity_g1_bonus": row["affinity"]["g1_bonus"],
                "affinity_component_score": round(row["components"]["affinity"], 3),
                "parent_parent_common_g1": " | ".join(row["affinity"]["parent_parent_common_g1"]),
                "distance_status": row["distance_viability"]["key"],
                "distance_tier": row["distance_viability"]["tier"],
                "distance_stars": row["distance_s_summary"]["total_stars"],
                "distance_carriers": row["distance_s_summary"]["carrier_count"],
                "distance_parent_carriers": row["distance_s_summary"]["parent_carrier_count"],
                "distance_support": row["distance_s_summary"]["weighted_support"],
                "distance_initial_required": row["distance_s_summary"]["initial_required_stars"],
                "distance_initial_met": row["distance_viability"]["is_initial_requirement_met"],
                "distance_initial_rank": row["distance_s_summary"]["initial_rank_label"],
                "distance_probability_a": round(100.0 * row["distance_s_summary"]["probability_reach_a"], 3),
                "distance_probability_s": round(100.0 * row["distance_s_summary"]["probability_reach_s"], 3),
                "surface_initial_rank": row["aptitude_summaries"]["surface"]["initial_rank_label"],
                "surface_probability_a": round(100.0 * row["aptitude_summaries"]["surface"]["probability_reach_a"], 3),
                "surface_probability_s": round(100.0 * row["aptitude_summaries"]["surface"]["probability_reach_s"], 3),
                "style_initial_rank": row["aptitude_summaries"]["style"]["initial_rank_label"],
                "style_probability_a": round(100.0 * row["aptitude_summaries"]["style"]["probability_reach_a"], 3),
                "style_probability_s": round(100.0 * row["aptitude_summaries"]["style"]["probability_reach_s"], 3),
                "blue": round(row["components"]["blue"], 3),
                "distance_s": round(row["components"]["distance_s"], 3),
                "pink_other": round(row["components"]["pink_other"], 3),
                "pink": round(row["components"]["pink"], 3),
                "white_skill": round(row["components"]["white_skill"], 3),
                "race_scenario": round(row["components"]["race_scenario"], 3),
                "unique": round(row["components"]["unique"], 3),
            }
            for rank, row in enumerate(pair_rows, 1)
        ]
        _write_csv(
            parent_pairs_csv,
            pair_csv_rows,
            ["rank", "score", "parent_1_id", "parent_1_rank_score", "parent_1", "parent_2_id", "parent_2_rank_score", "parent_2", "affinity_total", "affinity_base", "affinity_g1_bonus", "affinity_component_score", "parent_parent_common_g1", "distance_status", "distance_tier", "distance_stars", "distance_carriers", "distance_parent_carriers", "distance_support", "distance_initial_required", "distance_initial_met", "distance_initial_rank", "distance_probability_a", "distance_probability_s", "surface_initial_rank", "surface_probability_a", "surface_probability_s", "style_initial_rank", "style_probability_a", "style_probability_s", "blue", "distance_s", "pink_other", "pink", "white_skill", "race_scenario", "unique"],
        )

        future_csv_rows = [
            {
                "rank": rank,
                "score": round(row["score"], 4),
                "trained_chara_id": row["trained_chara_id"],
                "rank_score": row.get("rank_score"),
                "candidate": row["card_name"],
                "affinity_contribution": row["affinity_raw"],
                "future_parent_base_affinity": row["future_parent_base_affinity"],
                "future_branch_base_total": row["future_branch_base_total"],
                "affinity_mode": row["affinity_mode"],
                "g1_count": row["g1_count"],
                "affinity_component_score": round(row["components"]["affinity"], 3),
                "g1_component_score": round(row["components"]["g1_potential"], 3),
                "blue": round(row["components"]["blue"], 3),
                "pink": round(row["components"]["pink"], 3),
                "white_skill": round(row["components"]["white_skill"], 3),
                "white_generation": round(row["components"].get("white_generation", 0.0), 3),
                "unique": round(row["components"]["unique"], 3),
            }
            for rank, row in enumerate(future_rows, 1)
        ]
        _write_csv(
            future_csv,
            future_csv_rows,
            ["rank", "score", "trained_chara_id", "rank_score", "candidate", "affinity_contribution", "future_parent_base_affinity", "future_branch_base_total", "affinity_mode", "g1_count", "affinity_component_score", "g1_component_score", "blue", "pink", "white_skill", "white_generation", "unique"],
        )

        log(f"Classement terminé : {rankings_json}")
        return OptimizerResult(
            rankings_json_path=rankings_json,
            parent_candidates_csv_path=parent_candidates_csv,
            parent_pairs_csv_path=parent_pairs_csv,
            future_grandparents_csv_path=future_csv,
            top_parent_candidates=tuple(serializable_branches),
            top_parent_pairs=tuple(serializable_pairs),
            top_future_grandparents=tuple(serializable_future),
            ace=ace,
            future_parent=future_parent,
            profile=payload["profile"],
            scoring_weights=payload["scoring_weights"],
        )
    finally:
        resolver.close()

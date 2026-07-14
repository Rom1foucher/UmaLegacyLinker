from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CONDITION_FIELDS = (
    "precondition_1",
    "condition_1",
    "precondition_2",
    "condition_2",
)

ATOM_PATTERN = re.compile(
    r"^(?P<variable>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<operator>==|!=|>=|<=|>|<)"
    r"(?P<value>-?\d+(?:\.\d+)?)$"
)

STYLE_LABELS = {
    1: "front_runner",
    2: "pace_chaser",
    3: "late_surger",
    4: "end_closer",
}
DISTANCE_LABELS = {1: "sprint", 2: "mile", 3: "medium", 4: "long"}
GROUND_LABELS = {1: "turf", 2: "dirt"}
GROUND_CONDITION_LABELS = {1: "firm", 2: "good", 3: "soft", 4: "heavy"}
ROTATION_LABELS = {1: "right_handed", 2: "left_handed"}
SLOPE_LABELS = {0: "flat", 1: "uphill", 2: "downhill"}

VALUE_LABELS: dict[str, dict[int, str]] = {
    "running_style": STYLE_LABELS,
    "distance_type": DISTANCE_LABELS,
    "ground_type": GROUND_LABELS,
    "ground_condition": GROUND_CONDITION_LABELS,
    "rotation": ROTATION_LABELS,
    "slope": SLOPE_LABELS,
    "season": {1: "spring_primary", 2: "summer", 3: "fall", 4: "winter", 5: "spring_secondary"},
    "weather": {1: "sunny", 2: "cloudy", 3: "rainy", 4: "snowy"},
    "is_basis_distance": {0: "non_standard", 1: "standard"},
    "is_badstart": {0: "normal_start", 1: "bad_start"},
    "is_lastspurt": {0: "not_last_spurt", 1: "last_spurt"},
    "is_overtake": {0: "not_overtaking", 1: "overtaking"},
    "is_temptation": {0: "not_tempted", 1: "tempted"},
    "is_surrounded": {0: "not_surrounded", 1: "surrounded"},
    "is_finalcorner": {0: "not_final_corner", 1: "final_corner"},
    "is_finalcorner_laterhalf": {0: "not_later_half", 1: "later_half"},
    "is_move_lane": {0: "no_lane_change", 1: "lane_change_1", 2: "lane_change_2"},
}

VARIABLE_CATEGORIES: dict[str, str] = {
    # Static race / course profile.
    "running_style": "ace_profile",
    "distance_type": "ace_profile",
    "ground_type": "ace_profile",
    "rotation": "course_static",
    "track_id": "course_static",
    "is_basis_distance": "course_static",
    "ground_condition": "course_static",
    "season": "course_static",
    "weather": "course_static",
    "grade": "course_static",
    "is_dirtgrade": "course_static",
    "post_number": "course_static",
    "lane_type": "course_static",
    # Race segment / track position.
    "phase": "race_segment",
    "phase_random": "race_segment",
    "phase_firsthalf_random": "race_segment",
    "phase_laterhalf_random": "race_segment",
    "distance_rate": "race_segment",
    "distance_rate_after_random": "race_segment",
    "remain_distance": "race_segment",
    "remain_distance_viewer_id": "race_segment",
    "corner": "race_segment",
    "corner_random": "race_segment",
    "all_corner_random": "race_segment",
    "straight_random": "race_segment",
    "last_straight_random": "race_segment",
    "straight_front_type": "race_segment",
    "is_finalcorner": "race_segment",
    "is_finalcorner_random": "race_segment",
    "is_finalcorner_laterhalf": "race_segment",
    "is_last_straight_onetime": "race_segment",
    "is_lastspurt": "race_segment",
    "lastspurt": "race_segment",
    "slope": "race_segment",
    "up_slope_random": "race_segment",
    "down_slope_random": "race_segment",
    # Position / order.
    "order": "position_order",
    "order_rate": "position_order",
    "order_rate_in20_continue": "position_order",
    "order_rate_out40_continue": "position_order",
    "order_rate_in80_continue": "position_order",
    "order_rate_out50_continue": "position_order",
    "order_rate_in50_continue": "position_order",
    "order_rate_out70_continue": "position_order",
    "distance_diff_top": "position_order",
    "distance_diff_rate": "position_order",
    "bashin_diff_behind": "position_order",
    "bashin_diff_infront": "position_order",
    "near_count": "position_order",
    "behind_near_lane_time": "position_order",
    "behind_near_lane_time_set1": "position_order",
    "infront_near_lane_time": "position_order",
    # Overtaking / change of order.
    "is_overtake": "overtake_flow",
    "overtake_target_time": "overtake_flow",
    "overtake_target_no_order_up_time": "overtake_flow",
    "change_order_onetime": "overtake_flow",
    "change_order_up_end_after": "overtake_flow",
    "change_order_up_finalcorner_after": "overtake_flow",
    "is_behind_in": "overtake_flow",
    "compete_fight_count": "overtake_flow",
    # Blocking and lane mechanics.
    "blocked_front": "blocking_lane",
    "blocked_front_continuetime": "blocking_lane",
    "blocked_side_continuetime": "blocking_lane",
    "is_surrounded": "blocking_lane",
    "is_move_lane": "blocking_lane",
    # Field composition.
    "running_style_count_same": "field_composition",
    "running_style_count_same_rate": "field_composition",
    "running_style_equal_popularity_one": "field_composition",
    "running_style_count_nige_otherself": "field_composition",
    "running_style_count_senko_otherself": "field_composition",
    "running_style_count_sashi_otherself": "field_composition",
    "running_style_count_oikomi_otherself": "field_composition",
    "temptation_opponent_count_behind": "field_composition",
    "temptation_opponent_count_infront": "field_composition",
    "running_style_temptation_opponent_count_nige": "field_composition",
    "running_style_temptation_opponent_count_senko": "field_composition",
    "running_style_temptation_opponent_count_sashi": "field_composition",
    "running_style_temptation_opponent_count_oikomi": "field_composition",
    "same_skill_horse_count": "field_composition",
    "is_exist_chara_id": "field_composition",
    # State / resources.
    "hp_per": "runner_state",
    "base_power": "runner_state",
    "motivation": "runner_state",
    "is_badstart": "runner_state",
    "temptation_count": "runner_state",
    "is_temptation": "runner_state",
    "accumulatetime": "runner_state",
    # Skill activation state.
    "activate_count_start": "skill_activation_state",
    "activate_count_middle": "skill_activation_state",
    "activate_count_end_after": "skill_activation_state",
    "activate_count_later_half": "skill_activation_state",
    "activate_count_heal": "skill_activation_state",
    "activate_count_all": "skill_activation_state",
    "is_activate_any_skill": "skill_activation_state",
    "is_other_character_activate_advantage_skill": "skill_activation_state",
    # Random selectors / engine helpers.
    "random_lot": "random_selector",
    "always": "engine_helper",
    "popularity": "race_context",
}

FACTOR_TARGET_LABELS = {
    1: "speed",
    2: "stamina",
    3: "power",
    4: "guts",
    5: "wit",
    6: "skill_points",
    11: "turf_aptitude",
    12: "dirt_aptitude",
    21: "sprint_aptitude",
    22: "mile_aptitude",
    23: "medium_aptitude",
    24: "long_aptitude",
    31: "front_runner_aptitude",
    32: "pace_chaser_aptitude",
    33: "late_surger_aptitude",
    34: "end_closer_aptitude",
    41: "skill_hint",
    51: "unknown_event_effect",
    61: "speed_secondary",
    62: "stamina_secondary",
    63: "power_secondary",
    64: "guts_secondary",
    65: "wit_secondary",
}


@dataclass(frozen=True)
class SkillCatalogResult:
    skills_path: Path
    condition_types_path: Path
    weights_template_path: Path
    race_factor_skills_path: Path
    skill_count: int
    white_skill_group_count: int
    condition_variable_count: int
    distinct_expression_count: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_tables(connection: sqlite3.Connection, tables: Iterable[str]) -> None:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    missing = [table for table in tables if table not in existing]
    if missing:
        raise RuntimeError("Tables MDB manquantes : " + ", ".join(sorted(missing)))


def text_map(connection: sqlite3.Connection, category: int) -> dict[int, str]:
    return {
        int(row[0]): str(row[1])
        for row in connection.execute(
            'SELECT "index", text FROM text_data WHERE category = ?', (category,)
        )
    }


def json_write(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_number(raw: str) -> int | float:
    if "." in raw:
        return float(raw)
    return int(raw)


def parse_condition(expression: str | None) -> dict[str, Any]:
    raw = (expression or "").strip()
    if not raw:
        return {
            "raw": "",
            "or_groups": [],
            "variables": [],
            "fully_parsed": True,
        }

    variables: set[str] = set()
    groups: list[list[dict[str, Any]]] = []
    fully_parsed = True
    for raw_group in raw.split("@"):
        atoms: list[dict[str, Any]] = []
        for raw_atom in raw_group.split("&"):
            atom_text = raw_atom.strip()
            match = ATOM_PATTERN.fullmatch(atom_text)
            if not match:
                fully_parsed = False
                atoms.append({"raw": atom_text, "parsed": False})
                continue
            variable = match.group("variable")
            value = parse_number(match.group("value"))
            variables.add(variable)
            atom: dict[str, Any] = {
                "raw": atom_text,
                "parsed": True,
                "variable": variable,
                "operator": match.group("operator"),
                "value": value,
                "category": VARIABLE_CATEGORIES.get(variable, "uncategorized"),
            }
            if isinstance(value, int):
                label = VALUE_LABELS.get(variable, {}).get(value)
                if label:
                    atom["value_label"] = label
            atoms.append(atom)
        groups.append(atoms)
    return {
        "raw": raw,
        "or_groups": groups,
        "variables": sorted(variables),
        "fully_parsed": fully_parsed,
    }


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value.lower()).strip("_")
    return slug or "unnamed_skill"


def extract_effects(row: sqlite3.Row) -> list[dict[str, Any]]:
    activations: list[dict[str, Any]] = []
    for activation_slot in (1, 2):
        effects: list[dict[str, Any]] = []
        for effect_slot in (1, 2, 3):
            ability_type = int(row[f"ability_type_{activation_slot}_{effect_slot}"])
            if ability_type == 0:
                continue
            effects.append(
                {
                    "effect_slot": effect_slot,
                    "ability_type": ability_type,
                    "ability_value_usage": int(
                        row[f"ability_value_usage_{activation_slot}_{effect_slot}"]
                    ),
                    "additional_activate_type": int(
                        row[f"additional_activate_type_{activation_slot}_{effect_slot}"]
                    ),
                    "ability_value_level_usage": int(
                        row[f"ability_value_level_usage_{activation_slot}_{effect_slot}"]
                    ),
                    "float_ability_value": int(
                        row[f"float_ability_value_{activation_slot}_{effect_slot}"]
                    ),
                    "target_type": int(
                        row[f"target_type_{activation_slot}_{effect_slot}"]
                    ),
                    "target_value": int(
                        row[f"target_value_{activation_slot}_{effect_slot}"]
                    ),
                }
            )
        if effects or row[f"condition_{activation_slot}"] or row[f"precondition_{activation_slot}"]:
            activations.append(
                {
                    "activation_slot": activation_slot,
                    "precondition": parse_condition(
                        str(row[f"precondition_{activation_slot}"])
                    ),
                    "condition": parse_condition(str(row[f"condition_{activation_slot}"])),
                    "float_ability_time": int(
                        row[f"float_ability_time_{activation_slot}"]
                    ),
                    "ability_time_usage": int(
                        row[f"ability_time_usage_{activation_slot}"]
                    ),
                    "float_cooldown_time": int(
                        row[f"float_cooldown_time_{activation_slot}"]
                    ),
                    "effects": effects,
                }
            )
    return activations


def collect_static_constraints(parsed_conditions: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract obvious profile constraints without pretending to model dynamic logic."""
    result: dict[str, set[str]] = {
        "styles": set(),
        "distances": set(),
        "surfaces": set(),
    }
    has_dynamic = False
    categories: set[str] = set()
    for parsed in parsed_conditions:
        for group in parsed.get("or_groups", []):
            for atom in group:
                if not atom.get("parsed"):
                    has_dynamic = True
                    continue
                variable = atom["variable"]
                category = atom["category"]
                categories.add(category)
                if atom["operator"] == "==" and isinstance(atom["value"], int):
                    value = int(atom["value"])
                    if variable == "running_style" and value in STYLE_LABELS:
                        result["styles"].add(STYLE_LABELS[value])
                    elif variable == "distance_type" and value in DISTANCE_LABELS:
                        result["distances"].add(DISTANCE_LABELS[value])
                    elif variable == "ground_type" and value in GROUND_LABELS:
                        result["surfaces"].add(GROUND_LABELS[value])
                if category not in {"ace_profile", "course_static", "engine_helper"}:
                    has_dynamic = True
    return {
        "explicit_styles": sorted(result["styles"]),
        "explicit_distances": sorted(result["distances"]),
        "explicit_surfaces": sorted(result["surfaces"]),
        "condition_categories": sorted(categories),
        "contains_dynamic_race_logic": has_dynamic,
    }


def generate_skill_catalogs(
    master_path: str | Path,
    output_dir: str | Path,
    logger: Any | None = None,
) -> SkillCatalogResult:
    log = logger or (lambda _message: None)
    master = Path(master_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not master.is_file():
        raise RuntimeError(f"MDB introuvable : {master}")
    destination.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(f"file:{master.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        require_tables(
            connection,
            (
                "skill_data",
                "text_data",
                "succession_factor",
                "succession_factor_effect",
            ),
        )
        skill_names = text_map(connection, 47)
        skill_descriptions = text_map(connection, 48)
        factor_names = text_map(connection, 147)
        factor_descriptions = text_map(connection, 172)

        white_groups: dict[int, dict[str, Any]] = {}
        for row in connection.execute(
            """
            SELECT factor_id, factor_group_id, rarity
            FROM succession_factor
            WHERE factor_type = 4
            ORDER BY factor_group_id, rarity
            """
        ):
            group_id = int(row["factor_group_id"])
            factor_id = int(row["factor_id"])
            group = white_groups.setdefault(
                group_id,
                {
                    "factor_group_id": group_id,
                    "spark_name": factor_names.get(
                        factor_id, f"Unknown white skill Spark {group_id}"
                    ),
                    "description": factor_descriptions.get(factor_id, ""),
                    "factor_ids_by_stars": {},
                },
            )
            group["factor_ids_by_stars"][str(int(row["rarity"]))] = factor_id

        skill_rows = list(connection.execute("SELECT * FROM skill_data ORDER BY id"))
        skills_by_group: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in skill_rows:
            skills_by_group[int(row["group_id"])].append(row)

        for group_id, group in white_groups.items():
            candidates = skills_by_group.get(group_id, [])
            exact = [
                row
                for row in candidates
                if skill_names.get(int(row["id"])) == group["spark_name"]
            ]
            selected = exact[0] if len(exact) == 1 else None
            group["inherit_skill_id"] = int(selected["id"]) if selected else None
            group["mapping_status"] = (
                "exact_name_match"
                if selected
                else ("no_skill_candidates" if not candidates else "ambiguous_or_renamed")
            )
            group["candidate_skill_ids"] = [int(row["id"]) for row in candidates]
            group["catalog_key"] = slugify(group["spark_name"])

        expression_counter: Counter[str] = Counter()
        variable_usage: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "occurrences": 0,
                "skill_ids": set(),
                "operators": Counter(),
                "values": Counter(),
                "examples": [],
            }
        )
        skills_payload: list[dict[str, Any]] = []

        for row in skill_rows:
            skill_id = int(row["id"])
            parsed_by_field: dict[str, Any] = {}
            all_parsed: list[dict[str, Any]] = []
            for field in CONDITION_FIELDS:
                expression = str(row[field] or "")
                parsed = parse_condition(expression)
                parsed_by_field[field] = parsed
                all_parsed.append(parsed)
                if expression:
                    expression_counter[expression] += 1
                for group in parsed["or_groups"]:
                    for atom in group:
                        if not atom.get("parsed"):
                            continue
                        variable = str(atom["variable"])
                        usage = variable_usage[variable]
                        usage["occurrences"] += 1
                        usage["skill_ids"].add(skill_id)
                        usage["operators"][str(atom["operator"])] += 1
                        usage["values"][str(atom["value"])] += 1
                        if len(usage["examples"]) < 8:
                            usage["examples"].append(
                                {
                                    "skill_id": skill_id,
                                    "skill_name": skill_names.get(
                                        skill_id, f"Unknown skill {skill_id}"
                                    ),
                                    "field": field,
                                    "expression": expression,
                                }
                            )

            white_group = white_groups.get(int(row["group_id"]))
            skill_entry: dict[str, Any] = {
                "skill_id": skill_id,
                "group_id": int(row["group_id"]),
                "name": skill_names.get(skill_id, f"Unknown skill {skill_id}"),
                "description": skill_descriptions.get(skill_id, ""),
                "rarity": int(row["rarity"]),
                "grade_value": int(row["grade_value"]),
                "skill_category": int(row["skill_category"]),
                "tag_id": str(row["tag_id"]),
                "is_general_skill": bool(row["is_general_skill"]),
                "disable_singlemode": bool(row["disable_singlemode"]),
                "conditions": parsed_by_field,
                "profile_hints": collect_static_constraints(all_parsed),
                "activations": extract_effects(row),
                "white_spark": None,
            }
            if white_group:
                skill_entry["white_spark"] = {
                    "catalog_key": white_group["catalog_key"],
                    "spark_name": white_group["spark_name"],
                    "factor_group_id": white_group["factor_group_id"],
                    "factor_ids_by_stars": white_group["factor_ids_by_stars"],
                    "is_inherited_hint_variant": white_group["inherit_skill_id"] == skill_id,
                    "mapping_status": white_group["mapping_status"],
                }
            skills_payload.append(skill_entry)

        variable_payload: list[dict[str, Any]] = []
        for variable in sorted(variable_usage):
            usage = variable_usage[variable]
            raw_values = usage["values"]
            numeric_values: list[int | float | str] = []
            for raw in sorted(raw_values, key=lambda value: float(value)):
                try:
                    numeric_values.append(parse_number(raw))
                except ValueError:
                    numeric_values.append(raw)
            labels = VALUE_LABELS.get(variable, {})
            variable_payload.append(
                {
                    "name": variable,
                    "display_name": variable.replace("_", " "),
                    "category": VARIABLE_CATEGORIES.get(variable, "uncategorized"),
                    "occurrences": int(usage["occurrences"]),
                    "skill_count": len(usage["skill_ids"]),
                    "operators": dict(sorted(usage["operators"].items())),
                    "values": numeric_values,
                    "value_labels": {str(key): value for key, value in labels.items()},
                    "examples": usage["examples"],
                }
            )

        categories: dict[str, list[str]] = defaultdict(list)
        for variable in variable_payload:
            categories[variable["category"]].append(variable["name"])

        metadata = {
            "schema_version": 1,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "master_file": master.name,
            "master_sha256": sha256_file(master),
            "important": (
                "IDs are snapshots from this MDB. Match future updates primarily by "
                "catalog_key/spark_name, then refresh IDs from the new MDB."
            ),
        }

        white_group_payload = sorted(
            white_groups.values(), key=lambda item: item["spark_name"].casefold()
        )
        skills_document = {
            "metadata": metadata,
            "summary": {
                "skill_count": len(skills_payload),
                "white_skill_spark_group_count": len(white_group_payload),
                "skills_with_any_condition": sum(
                    any(skill["conditions"][field]["raw"] for field in CONDITION_FIELDS)
                    for skill in skills_payload
                ),
            },
            "condition_grammar": {
                "or_separator": "@",
                "and_separator": "&",
                "atom_pattern": "variable operator numeric_value",
                "operators": ["==", "!=", ">=", "<=", ">", "<"],
                "parentheses_present": False,
            },
            "white_skill_spark_groups": white_group_payload,
            "skills": skills_payload,
        }

        condition_document = {
            "metadata": metadata,
            "summary": {
                "condition_variable_count": len(variable_payload),
                "distinct_expression_count": len(expression_counter),
                "condition_occurrence_count": sum(expression_counter.values()),
                "fully_supported_grammar": all(
                    skill["conditions"][field]["fully_parsed"]
                    for skill in skills_payload
                    for field in CONDITION_FIELDS
                ),
            },
            "grammar": skills_document["condition_grammar"],
            "categories": {
                category: sorted(variables)
                for category, variables in sorted(categories.items())
            },
            "variables": variable_payload,
            "distinct_expressions": [
                {"expression": expression, "occurrences": count}
                for expression, count in sorted(
                    expression_counter.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        }

        axes = {
            "surfaces": ["turf", "dirt"],
            "distances": ["sprint", "mile", "medium", "long"],
            "styles": [
                "front_runner",
                "pace_chaser",
                "late_surger",
                "end_closer",
            ],
        }
        weight_entries: dict[str, Any] = {}
        for group in white_group_payload:
            matrix = {
                surface: {
                    distance: {style: None for style in axes["styles"]}
                    for distance in axes["distances"]
                }
                for surface in axes["surfaces"]
            }
            inherited_id = group["inherit_skill_id"]
            inherited_skill = next(
                (skill for skill in skills_payload if skill["skill_id"] == inherited_id),
                None,
            )
            weight_entries[group["catalog_key"]] = {
                "spark_name": group["spark_name"],
                "current_mdb": {
                    "factor_group_id": group["factor_group_id"],
                    "factor_ids_by_stars": group["factor_ids_by_stars"],
                    "inherit_skill_id": inherited_id,
                    "mapping_status": group["mapping_status"],
                },
                "description": (
                    inherited_skill["description"] if inherited_skill else group["description"]
                ),
                "raw_conditions": (
                    inherited_skill["conditions"] if inherited_skill else None
                ),
                "automatic_profile_hints": (
                    inherited_skill["profile_hints"] if inherited_skill else None
                ),
                "default_weight": None,
                "weight_matrix": matrix,
                "notes": "",
            }

        weights_document = {
            "metadata": {
                **metadata,
                "purpose": (
                    "Manual relevance weights for white skill Sparks. Values are expected "
                    "between 0.0 (useless) and 1.0 (top priority), but the scorer may accept "
                    "values above 1.0 for exceptional skills."
                ),
            },
            "axes": axes,
            "fallback": {
                "unset_cell": "use default_weight",
                "unset_default_weight": 0.0,
            },
            "skills": weight_entries,
        }

        # Race factors that grant a skill hint are separated because most race Sparks are weak,
        # while a matching green skill may be decisive for a target course.
        race_factor_groups: dict[int, dict[str, Any]] = {}
        for row in connection.execute(
            """
            SELECT factor_id, factor_group_id, rarity
            FROM succession_factor
            WHERE factor_type = 5
            ORDER BY factor_group_id, rarity
            """
        ):
            factor_id = int(row["factor_id"])
            group_id = int(row["factor_group_id"])
            rarity = int(row["rarity"])
            group = race_factor_groups.setdefault(
                group_id,
                {
                    "factor_group_id": group_id,
                    "race_factor_name": factor_names.get(
                        factor_id, f"Unknown race factor {group_id}"
                    ),
                    "description": factor_descriptions.get(factor_id, ""),
                    "factor_ids_by_stars": {},
                    "effects_by_stars": {},
                    "granted_skills": {},
                },
            )
            group["factor_ids_by_stars"][str(rarity)] = factor_id
            effects: list[dict[str, Any]] = []
            for effect in connection.execute(
                """
                SELECT target_type, value_1, value_2
                FROM succession_factor_effect
                WHERE factor_group_id = ? AND effect_id = ?
                ORDER BY id
                """,
                (group_id, rarity),
            ):
                target_type = int(effect["target_type"])
                value_1 = int(effect["value_1"])
                entry: dict[str, Any] = {
                    "target_type": target_type,
                    "target_label": FACTOR_TARGET_LABELS.get(
                        target_type, f"unknown_target_{target_type}"
                    ),
                    "value_1": value_1,
                    "value_2": int(effect["value_2"]),
                }
                if target_type == 41:
                    entry["skill_id"] = value_1
                    entry["skill_name"] = skill_names.get(
                        value_1, f"Unknown skill {value_1}"
                    )
                    matching = next(
                        (skill for skill in skills_payload if skill["skill_id"] == value_1),
                        None,
                    )
                    if matching:
                        entry["skill_description"] = matching["description"]
                        entry["skill_conditions"] = matching["conditions"]
                        entry["skill_profile_hints"] = matching["profile_hints"]
                    group["granted_skills"][str(value_1)] = {
                        "skill_id": value_1,
                        "name": entry["skill_name"],
                    }
                effects.append(entry)
            group["effects_by_stars"][str(rarity)] = effects

        race_factor_payload = []
        for group in race_factor_groups.values():
            group["granted_skills"] = list(group["granted_skills"].values())
            group["grants_skill_hint"] = bool(group["granted_skills"])
            race_factor_payload.append(group)
        race_factor_payload.sort(key=lambda item: item["race_factor_name"].casefold())
        race_factor_document = {
            "metadata": {
                **metadata,
                "scoring_note": (
                    "Race Sparks should receive a low base weight. When grants_skill_hint is "
                    "true, score the granted skill through the same target-course relevance "
                    "rules as green/white skills."
                ),
            },
            "summary": {
                "race_factor_group_count": len(race_factor_payload),
                "groups_granting_skill_hint": sum(
                    group["grants_skill_hint"] for group in race_factor_payload
                ),
            },
            "race_factors": race_factor_payload,
        }

        skills_path = destination / "skill_condition_catalog.json"
        condition_types_path = destination / "condition_type_catalog.json"
        weights_template_path = destination / "white_skill_weights_template.json"
        race_factor_skills_path = destination / "race_factor_skill_catalog.json"
        json_write(skills_path, skills_document)
        json_write(condition_types_path, condition_document)
        json_write(weights_template_path, weights_document)
        json_write(race_factor_skills_path, race_factor_document)

        log(
            "Catalogue skills : "
            f"{len(skills_payload)} skills, {len(variable_payload)} variables de condition, "
            f"{len(white_group_payload)} groupes de white Sparks."
        )
        return SkillCatalogResult(
            skills_path=skills_path,
            condition_types_path=condition_types_path,
            weights_template_path=weights_template_path,
            race_factor_skills_path=race_factor_skills_path,
            skill_count=len(skills_payload),
            white_skill_group_count=len(white_group_payload),
            condition_variable_count=len(variable_payload),
            distinct_expression_count=len(expression_counter),
        )
    finally:
        connection.close()

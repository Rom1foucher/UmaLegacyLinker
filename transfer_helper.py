from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from course_presets import ordered_course_presets
from parent_optimizer import (
    DISTANCES,
    STYLES,
    SURFACES,
    AffinityResolver,
    OptimizerError,
    _affinity_score,
    _blue_score,
    _branch_affinity,
    _branch_inheritance_affinities,
    _candidate_identity,
    _factor_list,
    _future_grandparent_pink_score,
    _future_grandparent_white_score,
    _lineage_members,
    _member_g1,
    _mode_weights,
    _pink_score,
    _race_scenario_score,
    _race_skill_map,
    _selected_weight_lookup,
    _unique_score,
    _weighted_total,
    _white_generation_support_score,
    _white_score,
    load_ace_options,
)


class TransferHelperError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransferHelperResult:
    report_json_path: Path
    candidates_csv_path: Path
    summary_txt_path: Path
    safe_transfer_count: int
    review_count: int
    likely_keep_count: int
    keep_count: int
    records: tuple[dict[str, Any], ...]
    settings: dict[str, Any]


@dataclass(frozen=True)
class ProfileContext:
    key: str
    label: str
    surface: str
    distance: str
    style: str
    course_key: str | None = None
    course_conditions: dict[str, Any] | None = None


@dataclass
class DominanceAccumulator:
    parent_no_worse: bool = True
    grandparent_no_worse: bool = True
    pair_support_no_worse: bool = True
    parent_sum_delta: float = 0.0
    grandparent_sum_delta: float = 0.0
    parent_count: int = 0
    grandparent_count: int = 0
    minimum_delta: float = math.inf
    maximum_delta: float = -math.inf

    def update_parent(self, loser_score: float, winner_score: float, tolerance: float) -> None:
        delta = float(winner_score) - float(loser_score)
        if delta < -float(tolerance):
            self.parent_no_worse = False
        self.parent_sum_delta += delta
        self.parent_count += 1
        self.minimum_delta = min(self.minimum_delta, delta)
        self.maximum_delta = max(self.maximum_delta, delta)

    def update_grandparent(self, loser_score: float, winner_score: float, tolerance: float) -> None:
        delta = float(winner_score) - float(loser_score)
        if delta < -float(tolerance):
            self.grandparent_no_worse = False
        self.grandparent_sum_delta += delta
        self.grandparent_count += 1
        self.minimum_delta = min(self.minimum_delta, delta)
        self.maximum_delta = max(self.maximum_delta, delta)

    @property
    def combined_count(self) -> int:
        return self.parent_count + self.grandparent_count

    @property
    def mean_delta(self) -> float:
        if self.combined_count <= 0:
            return 0.0
        return (self.parent_sum_delta + self.grandparent_sum_delta) / self.combined_count

    def as_dict(self) -> dict[str, Any]:
        return {
            "parent_no_worse": self.parent_no_worse,
            "grandparent_no_worse": self.grandparent_no_worse,
            "pair_support_no_worse": self.pair_support_no_worse,
            "parent_mean_delta": round(self.parent_sum_delta / self.parent_count, 6) if self.parent_count else 0.0,
            "grandparent_mean_delta": round(self.grandparent_sum_delta / self.grandparent_count, 6) if self.grandparent_count else 0.0,
            "combined_mean_delta": round(self.mean_delta, 6),
            "minimum_delta": round(self.minimum_delta, 6) if math.isfinite(self.minimum_delta) else 0.0,
            "maximum_delta": round(self.maximum_delta, 6) if math.isfinite(self.maximum_delta) else 0.0,
            "evaluated_parent_contexts": self.parent_count,
            "evaluated_grandparent_contexts": self.grandparent_count,
        }


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


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _unique_signature(veteran: dict[str, Any]) -> tuple[str, ...]:
    signatures: list[str] = []
    for factor in _factor_list(veteran, "unique"):
        group_id = factor.get("factor_group_id")
        name = str(factor.get("name") or "").strip()
        signatures.append(f"group:{group_id}" if group_id not in (None, 0, "") else f"name:{name}")
    return tuple(sorted(signatures))


def comparison_group_key(veteran: dict[str, Any]) -> str:
    """Return the conservative replacement group for a veteran.

    Card ID is deliberately preferred over character ID: alternate costumes can
    have different inherited unique skills and must never replace one another.
    The unique signature is retained as a safety check for malformed exports.
    """
    card_id = int(veteran.get("card_id") or 0)
    chara_id = int(veteran.get("chara_id") or 0)
    unique = ",".join(_unique_signature(veteran)) or "none"
    if card_id > 0:
        return f"card:{card_id}|unique:{unique}"
    return f"chara:{chara_id}|unique:{unique}"


def _build_profile_contexts(
    course_payload: dict[str, Any] | None,
    include_course_presets: bool,
    *,
    upcoming_cm_limit: int = 5,
    include_team_trials: bool = True,
    include_generic_profiles: bool = False,
) -> list[ProfileContext]:
    """Build the deliberately narrow Transfer Helper evaluation scope.

    The cleanup audit must reflect near-term practical uses rather than every
    theoretical surface/distance combination. By default it evaluates only the
    first five upcoming Champion Meetings and the five generic Team Trials
    categories. Other course presets remain available to the normal optimiser.
    """

    contexts: list[ProfileContext] = []
    if include_generic_profiles:
        contexts.extend(
            ProfileContext(
                key=f"generic:{surface}:{distance}:{style}",
                label=f"Generic · {surface}/{distance}/{style}",
                surface=surface,
                distance=distance,
                style=style,
            )
            for surface in SURFACES
            for distance in DISTANCES
            for style in STYLES
        )

    if not include_course_presets or not course_payload:
        return contexts

    ordered = ordered_course_presets(course_payload)
    upcoming = [
        (course_key, course)
        for course_key, course in ordered
        if str(course.get("category") or "") == "champions_meeting_upcoming"
    ][: max(0, int(upcoming_cm_limit))]
    team_trials = [
        (course_key, course)
        for course_key, course in ordered
        if include_team_trials
        and str(course.get("category") or "") == "team_trials"
    ]

    for course_key, course in [*upcoming, *team_trials]:
        profile = course.get("profile") or {}
        surface = str(profile.get("surface") or "")
        distance = str(profile.get("distance") or "")
        if surface not in SURFACES or distance not in DISTANCES:
            continue
        label = str(course.get("label") or course_key)
        conditions = dict(course.get("conditions") or {})
        for style in STYLES:
            contexts.append(
                ProfileContext(
                    key=f"course:{course_key}:{style}",
                    label=f"{label} · {style}",
                    surface=surface,
                    distance=distance,
                    style=style,
                    course_key=str(course_key),
                    course_conditions=conditions,
                )
            )
    return contexts


def _ace_variants(
    resolver: AffinityResolver,
    ace_options: Iterable[Any],
    surface: str,
    distance: str,
    style: str,
) -> list[dict[str, Any]]:
    variants: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for option in ace_options:
        try:
            ace = resolver.ace_details(int(option.card_id), surface, distance, style)
        except (OptimizerError, KeyError, TypeError, ValueError):
            continue
        aptitudes = ace.get("target_aptitudes") or {}
        signature = (
            int(ace.get("chara_id") or 0),
            int(((aptitudes.get("surface") or {}).get("rank")) or 0),
            int(((aptitudes.get("distance") or {}).get("rank")) or 0),
            int(((aptitudes.get("style") or {}).get("rank")) or 0),
        )
        variants.setdefault(signature, ace)
    return list(variants.values())


def _rank_percentiles(scores: dict[int, float | None]) -> dict[int, float]:
    valid = [(index, float(score)) for index, score in scores.items() if score is not None]
    if not valid:
        return {}
    valid.sort(key=lambda item: item[1], reverse=True)
    denominator = max(1, len(valid) - 1)
    result: dict[int, float] = {}
    position = 0
    while position < len(valid):
        end = position + 1
        while end < len(valid) and abs(valid[end][1] - valid[position][1]) <= 1e-9:
            end += 1
        percentile = 100.0 * position / denominator
        for index in range(position, end):
            result[valid[index][0]] = percentile
        position = end
    return result



def _profile_quality_metrics(
    scores: dict[int, float | None],
    percentiles: dict[int, float],
    *,
    absolute_floor: float,
    absolute_weight: float,
    leader_weight: float,
    percentile_weight: float,
) -> dict[int, dict[str, float]]:
    valid = [float(score) for score in scores.values() if score is not None]
    if not valid:
        return {}
    leader = max(valid)
    weight_total = max(1e-9, absolute_weight + leader_weight + percentile_weight)
    result: dict[int, dict[str, float]] = {}
    for index, raw_score in scores.items():
        if raw_score is None:
            continue
        score = float(raw_score)
        absolute_component = max(0.0, min(1.0, score / max(1e-9, absolute_floor)))
        leader_component = max(0.0, min(1.0, score / max(1e-9, leader)))
        percentile = float(percentiles.get(index, 100.0))
        percentile_component = max(0.0, min(1.0, 1.0 - percentile / 100.0))
        utility = (
            absolute_component * absolute_weight
            + leader_component * leader_weight
            + percentile_component * percentile_weight
        ) / weight_total
        result[index] = {
            "utility": utility,
            "relative_to_leader": leader_component,
            "leader_score": leader,
            "score_gap_to_leader": leader - score,
        }
    return result

def _is_globally_competitive(
    score: float | None,
    quality: dict[str, float] | None,
    *,
    competitive_score_floor: float,
    competitive_utility_floor: float,
    minimum_absolute_floor_ratio: float,
) -> bool:
    if score is None or not quality:
        return False
    return (
        float(score) >= float(competitive_score_floor) * float(minimum_absolute_floor_ratio)
        and float(quality.get("utility", 0.0)) >= float(competitive_utility_floor)
    )


def _update_group_dominance_for_scores(
    group_indices: list[int],
    relations: dict[tuple[int, int], DominanceAccumulator],
    parent_scores: dict[int, float | None],
    grandparent_scores: dict[int, float | None],
    parent_quality: dict[int, dict[str, float]],
    grandparent_quality: dict[int, dict[str, float]],
    *,
    competitive_score_floor: float,
    competitive_utility_floor: float,
    minimum_absolute_floor_ratio: float,
    dominance_tolerance: float,
) -> tuple[bool, bool]:
    """Update same-card dominance only in globally viable role contexts.

    A marginal advantage in a context where every copy of that card is globally
    outclassed must not preserve an otherwise redundant veteran. For example,
    the least-bad Mejiro Ryan on Dirt is irrelevant when no Ryan is competitive
    against the complete local parent pool on Dirt.
    """
    parent_viable = any(
        _is_globally_competitive(
            parent_scores.get(index),
            parent_quality.get(index),
            competitive_score_floor=competitive_score_floor,
            competitive_utility_floor=competitive_utility_floor,
            minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
        )
        for index in group_indices
    )
    grandparent_viable = any(
        _is_globally_competitive(
            grandparent_scores.get(index),
            grandparent_quality.get(index),
            competitive_score_floor=competitive_score_floor,
            competitive_utility_floor=competitive_utility_floor,
            minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
        )
        for index in group_indices
    )

    for loser_index in group_indices:
        for winner_index in group_indices:
            if loser_index == winner_index:
                continue
            relation = relations.get((loser_index, winner_index))
            if relation is None:
                continue
            if parent_viable:
                loser_parent = parent_scores.get(loser_index)
                winner_parent = parent_scores.get(winner_index)
                if loser_parent is not None and winner_parent is not None:
                    relation.update_parent(
                        loser_parent,
                        winner_parent,
                        dominance_tolerance,
                    )
            if grandparent_viable:
                loser_gp = grandparent_scores.get(loser_index)
                winner_gp = grandparent_scores.get(winner_index)
                if loser_gp is not None and winner_gp is not None:
                    relation.update_grandparent(
                        loser_gp,
                        winner_gp,
                        dominance_tolerance,
                    )
    return parent_viable, grandparent_viable


def _update_best(
    record: dict[str, Any],
    role: str,
    score: float,
    context: ProfileContext,
    ace: dict[str, Any],
) -> None:
    key = f"_best_{role}_score"
    if float(score) <= float(record.get(key, -1.0)):
        return
    record[key] = float(score)
    record[f"_best_{role}_context"] = {
        "context_key": context.key,
        "profile": context.label,
        "surface": context.surface,
        "distance": context.distance,
        "style": context.style,
        "course_key": context.course_key,
        "ace_card_id": ace.get("card_id"),
        "ace_chara_id": ace.get("chara_id"),
        "ace": ace.get("card_name") or ace.get("uma_name"),
    }


def _dominance_candidates(
    records: list[dict[str, Any]],
    relations: dict[tuple[int, int], DominanceAccumulator],
    dominance_mean_margin: float,
) -> dict[int, list[tuple[int, DominanceAccumulator]]]:
    result: dict[int, list[tuple[int, DominanceAccumulator]]] = defaultdict(list)
    for (loser_index, winner_index), relation in relations.items():
        parent_role_ok = relation.parent_count == 0 or relation.parent_no_worse
        grandparent_role_ok = (
            relation.grandparent_count == 0 or relation.grandparent_no_worse
        )
        if not (
            parent_role_ok
            and grandparent_role_ok
            and relation.pair_support_no_worse
            and relation.combined_count > 0
            and relation.mean_delta >= float(dominance_mean_margin)
        ):
            continue
        result[loser_index].append((winner_index, relation))
    for loser_index, candidates in result.items():
        candidates.sort(
            key=lambda item: (
                item[1].mean_delta,
                float(records[item[0]].get("_best_parent_score", 0.0))
                + float(records[item[0]].get("_best_grandparent_score", 0.0)),
            ),
            reverse=True,
        )
    return result


def _role_evidence(
    profiles: list[dict[str, Any]],
    *,
    elite_utility_floor: float,
    competitive_utility_floor: float,
    competitive_score_floor: float,
    minimum_absolute_floor_ratio: float,
    minimum_competitive_contexts: int,
    minimum_distinct_profiles: int,
) -> dict[str, Any]:
    competitive = [
        profile
        for profile in profiles
        if float(profile.get("score", 0.0)) >= competitive_score_floor * minimum_absolute_floor_ratio
        and float(profile.get("utility", 0.0)) >= competitive_utility_floor
    ]
    elite = [
        profile
        for profile in profiles
        if float(profile.get("score", 0.0)) >= competitive_score_floor * minimum_absolute_floor_ratio
        and float(profile.get("utility", 0.0)) >= elite_utility_floor
    ]
    distinct_profiles = {
        str(profile.get("course_key") or profile.get("context_key") or "")
        for profile in competitive
    }
    repeated = (
        len(competitive) >= minimum_competitive_contexts
        and len(distinct_profiles) >= minimum_distinct_profiles
    )
    return {
        "elite": bool(elite),
        "repeated": repeated,
        "competitive_context_count": len(competitive),
        "competitive_distinct_profile_count": len(distinct_profiles),
        "elite_context_count": len(elite),
    }


def classify_transfer_records(
    records: list[dict[str, Any]],
    relations: dict[tuple[int, int], DominanceAccumulator],
    *,
    elite_utility_floor: float,
    competitive_utility_floor: float,
    competitive_score_floor: float,
    minimum_absolute_floor_ratio: float,
    minimum_competitive_contexts: int,
    minimum_distinct_profiles: int,
    dominance_mean_margin: float,
) -> None:
    """Assign safe_transfer/review/likely_keep/keep in place."""
    dominators = _dominance_candidates(records, relations, dominance_mean_margin)

    def resolve(index: int, seen: set[int] | None = None) -> tuple[int, DominanceAccumulator] | None:
        seen = set(seen or ())
        if index in seen:
            return None
        seen.add(index)
        candidates = dominators.get(index) or []
        if not candidates:
            return None
        winner_index, relation = candidates[0]
        nested = resolve(winner_index, seen)
        if nested is None:
            return winner_index, relation
        final_winner_index = nested[0]
        for direct_winner_index, direct_relation in candidates:
            if direct_winner_index == final_winner_index:
                return final_winner_index, direct_relation
        return winner_index, relation

    for index, record in enumerate(records):
        parent_profiles = list(record.get("_parent_profiles") or [])
        gp_profiles = list(record.get("_grandparent_profiles") or [])
        parent_evidence = _role_evidence(
            parent_profiles,
            elite_utility_floor=elite_utility_floor,
            competitive_utility_floor=competitive_utility_floor,
            competitive_score_floor=competitive_score_floor,
            minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
            minimum_competitive_contexts=minimum_competitive_contexts,
            minimum_distinct_profiles=minimum_distinct_profiles,
        )
        gp_evidence = _role_evidence(
            gp_profiles,
            elite_utility_floor=elite_utility_floor,
            competitive_utility_floor=competitive_utility_floor,
            competitive_score_floor=competitive_score_floor,
            minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
            minimum_competitive_contexts=minimum_competitive_contexts,
            minimum_distinct_profiles=minimum_distinct_profiles,
        )
        parent_competitive = bool(parent_evidence["elite"] or parent_evidence["repeated"])
        grandparent_competitive = bool(gp_evidence["elite"] or gp_evidence["repeated"])
        parent_plausible = parent_evidence["competitive_context_count"] > 0
        gp_plausible = gp_evidence["competitive_context_count"] > 0
        record["parent_competitive"] = parent_competitive
        record["grandparent_competitive"] = grandparent_competitive
        record["parent_evidence"] = parent_evidence
        record["grandparent_evidence"] = gp_evidence

        resolved = resolve(index)
        if resolved is not None:
            winner_index, relation = resolved
            winner = records[winner_index]
            record["status"] = "safe_transfer"
            record["reason_code"] = "strictly_dominated_same_card"
            record["dominated_by"] = {
                "trained_chara_id": winner.get("trained_chara_id"),
                "card_name": winner.get("card_name"),
                "uma_name": winner.get("uma_name"),
                "rank": winner.get("rank"),
                "rank_score": winner.get("rank_score"),
                "stats": winner.get("stats") or {},
                "grandparent_1": winner.get("grandparent_1"),
                "grandparent_2": winner.get("grandparent_2"),
                "mean_score_lead": round(relation.mean_delta, 4),
                "worst_context_delta": round(relation.minimum_delta, 4) if math.isfinite(relation.minimum_delta) else 0.0,
                "best_context_delta": round(relation.maximum_delta, 4) if math.isfinite(relation.maximum_delta) else 0.0,
                "viable_parent_comparisons": relation.parent_count,
                "viable_grandparent_comparisons": relation.grandparent_count,
            }
        elif parent_competitive or grandparent_competitive:
            record["status"] = "keep"
            record["reason_code"] = (
                "strong_grandparent_value"
                if grandparent_competitive and not parent_competitive
                else "strong_parent_value"
                if parent_competitive and not grandparent_competitive
                else "strong_value_in_multiple_roles"
            )
            record["dominated_by"] = None
        elif parent_plausible or gp_plausible:
            record["status"] = "likely_keep"
            record["reason_code"] = "narrow_or_single_context_niche"
            record["dominated_by"] = None
        else:
            record["status"] = "review"
            record["reason_code"] = "no_meaningful_role_detected"
            record["dominated_by"] = None


def analyze_transfer_candidates(
    master_path: str | Path,
    linked_veterans_path: str | Path,
    skill_weights_path: str | Path,
    race_factor_catalog_path: str | Path,
    skill_catalog_path: str | Path,
    output_dir: str | Path,
    *,
    course_weights_path: str | Path | None = None,
    scoring_config_path: str | Path | None = None,
    logger: Callable[[str], None] | None = None,
) -> TransferHelperResult:
    log = logger or _logger_default
    master = Path(master_path).expanduser().resolve()
    linked_path = Path(linked_veterans_path).expanduser().resolve()
    weights_path = Path(skill_weights_path).expanduser().resolve()
    race_catalog_path = Path(race_factor_catalog_path).expanduser().resolve()
    skill_catalog_path_resolved = Path(skill_catalog_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    course_path = Path(course_weights_path).expanduser().resolve() if course_weights_path else None
    config_path = (
        Path(scoring_config_path).expanduser().resolve()
        if scoring_config_path
        else Path(__file__).resolve().parent / "default_parent_scoring.json"
    )

    required = (master, linked_path, weights_path, race_catalog_path, skill_catalog_path_resolved, config_path)
    for path in required:
        if not path.is_file():
            raise TransferHelperError(f"Fichier requis introuvable : {path}")

    destination.mkdir(parents=True, exist_ok=True)
    log("Chargement des vétérans locaux et des profils de score du Transfer Helper…")
    linked_payload = _read_json(linked_path)
    weights_payload = _read_json(weights_path)
    race_catalog = _read_json(race_catalog_path)
    skill_catalog = _read_json(skill_catalog_path_resolved)
    config = _read_json(config_path)
    course_payload = _read_json(course_path) if course_path and course_path.is_file() else None
    veterans = list(linked_payload.get("veterans") or [])
    if not veterans:
        raise TransferHelperError("Aucun vétéran dans veterans_legacy_linked.json")

    helper_config = config.get("transfer_helper") or {}
    competitive_score_floor = float(helper_config.get("competitive_score_floor", 67.5))
    competitive_utility_floor = float(helper_config.get("competitive_utility_floor", 0.82))
    elite_utility_floor = float(helper_config.get("elite_utility_floor", 0.92))
    minimum_absolute_floor_ratio = float(helper_config.get("minimum_absolute_floor_ratio", 0.80))
    utility_absolute_weight = float(helper_config.get("utility_absolute_weight", 0.50))
    utility_leader_weight = float(helper_config.get("utility_leader_weight", 0.40))
    utility_percentile_weight = float(helper_config.get("utility_percentile_weight", 0.10))
    minimum_competitive_contexts = max(1, int(helper_config.get("minimum_competitive_contexts", 3)))
    minimum_distinct_profiles = max(1, int(helper_config.get("minimum_distinct_profiles", 2)))
    dominance_tolerance = float(helper_config.get("dominance_tolerance", 0.75))
    dominance_mean_margin = float(helper_config.get("dominance_mean_margin", 1.0))
    include_course_presets = bool(helper_config.get("include_course_presets", True))
    upcoming_cm_limit = max(0, int(helper_config.get("upcoming_cm_limit", 5)))
    include_team_trials = bool(helper_config.get("include_team_trials", True))
    include_generic_profiles = bool(helper_config.get("include_generic_profiles", False))
    settings = {
        "competitive_score_floor": competitive_score_floor,
        "competitive_utility_floor": competitive_utility_floor,
        "elite_utility_floor": elite_utility_floor,
        "minimum_absolute_floor_ratio": minimum_absolute_floor_ratio,
        "utility_absolute_weight": utility_absolute_weight,
        "utility_leader_weight": utility_leader_weight,
        "utility_percentile_weight": utility_percentile_weight,
        "minimum_competitive_contexts": minimum_competitive_contexts,
        "minimum_distinct_profiles": minimum_distinct_profiles,
        "dominance_tolerance": dominance_tolerance,
        "dominance_mean_margin": dominance_mean_margin,
        "include_course_presets": include_course_presets,
        "upcoming_cm_limit": upcoming_cm_limit,
        "include_team_trials": include_team_trials,
        "include_generic_profiles": include_generic_profiles,
        "course_preset_scope": "first five upcoming Champion Meetings and five Team Trials profiles by default",
        "replacement_scope": "same card ID and inherited unique signature only",
        "grandparent_affinity_mode": "optimistic constant ceiling; relative intrinsic ranking is target-independent",
        "dominance_context_scope": "same-card comparisons only count roles where at least one copy is globally competitive against the full local veteran pool",
    }

    contexts = _build_profile_contexts(
        course_payload,
        include_course_presets,
        upcoming_cm_limit=upcoming_cm_limit,
        include_team_trials=include_team_trials,
        include_generic_profiles=include_generic_profiles,
    )
    if not contexts:
        raise TransferHelperError(
            "Aucun profil actif pour le Transfer Helper. Activez les presets de course, "
            "les Team Trials ou les profils génériques dans transfer_helper."
        )
    settings["evaluated_profile_count"] = len({context.course_key or context.key for context in contexts})
    settings["evaluated_context_count"] = len(contexts)
    settings["evaluated_course_keys"] = list(
        dict.fromkeys(context.course_key for context in contexts if context.course_key)
    )
    groups: dict[str, list[int]] = defaultdict(list)
    reference_counts: Counter[int] = Counter()
    records: list[dict[str, Any]] = []
    for index, veteran in enumerate(veterans):
        group = comparison_group_key(veteran)
        groups[group].append(index)
        lineage = veteran.get("when_used_as_parent") or {}
        for position in ("grandparent_1", "grandparent_2"):
            local_id = (lineage.get(position) or {}).get("local_trained_chara_id")
            if isinstance(local_id, int):
                reference_counts[local_id] += 1
        record = {
            **_candidate_identity(veteran),
            "comparison_group": group,
            "same_card_copy_count": 0,
            "referenced_by_local_veterans": 0,
            "_best_parent_score": 0.0,
            "_best_grandparent_score": 0.0,
            "_best_parent_percentile": 100.0,
            "_best_grandparent_percentile": 100.0,
            "_parent_profiles": [],
            "_grandparent_profiles": [],
        }
        records.append(record)

    for index, record in enumerate(records):
        record["same_card_copy_count"] = len(groups[record["comparison_group"]])
        trained_id = record.get("trained_chara_id")
        record["referenced_by_local_veterans"] = reference_counts.get(trained_id, 0) if isinstance(trained_id, int) else 0

    relations: dict[tuple[int, int], DominanceAccumulator] = {}
    for indices in groups.values():
        if len(indices) < 2:
            continue
        for loser_index in indices:
            for winner_index in indices:
                if loser_index != winner_index:
                    relations[(loser_index, winner_index)] = DominanceAccumulator()

    # Pair-specific base compatibility is identical inside a same-card group. The
    # only pair support that can differ is G1 overlap, so compare it against every
    # possible local partner once and carry the result into the dominance rule.
    for (loser_index, winner_index), relation in relations.items():
        loser_g1 = _member_g1(veterans[loser_index])
        winner_g1 = _member_g1(veterans[winner_index])
        for partner_index, partner in enumerate(veterans):
            if partner_index in {loser_index, winner_index}:
                continue
            partner_g1 = _member_g1(partner)
            if len(winner_g1 & partner_g1) < len(loser_g1 & partner_g1):
                relation.pair_support_no_worse = False
                break

    resolver = AffinityResolver(master)
    ace_options = load_ace_options(master)
    race_skills = _race_skill_map(race_catalog)
    affinity_cfg = config.get("affinity") or {}
    g1_bonus_value = int(affinity_cfg.get("g1_common_bonus", 3))
    branch_thresholds = affinity_cfg.get("parent_branch_thresholds") or [[0, 0], [95, 100]]
    future_g1_thresholds = affinity_cfg.get("future_g1_thresholds") or [[0, 0], [20, 100]]
    parent_weights = _mode_weights(config, "parent_branch")
    grandparent_weights = _mode_weights(config, "future_grandparent")
    course_condition_config = config.get("course_conditions") or {}
    active_green_floor = float(course_condition_config.get("active_green_floor", 0.12))
    green_floors = {str(key): float(value) for key, value in (course_condition_config.get("floors") or {}).items()}
    green_modes = {str(key): str(value) for key, value in (course_condition_config.get("modes") or {}).items()}

    affinity_cache: dict[tuple[int, int], dict[str, Any]] = {}
    ace_cache: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    try:
        log(
            f"Évaluation de {len(veterans)} vétérans dans {len(contexts)} contextes de profil/catégorie…"
        )
        for context_index, context in enumerate(contexts, 1):
            cache_key = (context.surface, context.distance, context.style)
            aces = ace_cache.get(cache_key)
            if aces is None:
                aces = _ace_variants(
                    resolver,
                    ace_options,
                    context.surface,
                    context.distance,
                    context.style,
                )
                ace_cache[cache_key] = aces
            if not aces:
                continue

            weight_lookup, _weight_source, _diagnostics = _selected_weight_lookup(
                weights_payload,
                course_payload,
                skill_catalog,
                context.surface,
                context.distance,
                context.style,
                context.course_key,
                context.course_conditions or {},
                active_green_floor,
                green_floors,
                green_modes,
            )

            parent_static: list[dict[str, float]] = []
            gp_static: list[dict[str, float]] = []
            for veteran in veterans:
                parent_members = _lineage_members(veteran)
                blue, _ = _blue_score(parent_members, context.distance, config)
                race, _ = _race_scenario_score(
                    parent_members, weight_lookup, race_skills, config, "parent_branch"
                )
                unique, _ = _unique_score(parent_members, config, "parent_branch")
                parent_static.append(
                    {
                        "blue": blue,
                        "race_scenario": race,
                        "unique": unique,
                    }
                )

                own_member = [(veteran, "grandparent", "candidate")]
                gp_blue, _ = _blue_score(own_member, context.distance, config)
                gp_white, _ = _future_grandparent_white_score(
                    own_member, weight_lookup, config, race_skills
                )
                gp_generation, _ = _white_generation_support_score(
                    _lineage_members(veteran), weight_lookup, config
                )
                gp_unique, _ = _unique_score(
                    own_member, config, "future_grandparent"
                )
                gp_g1 = _affinity_score(
                    float(len(_member_g1(veteran))), future_g1_thresholds
                )
                gp_static.append(
                    {
                        "blue": gp_blue,
                        "white_skill": gp_white,
                        "white_generation": gp_generation,
                        "unique": gp_unique,
                        "g1_potential": gp_g1,
                        # An optimistic constant avoids falsely discarding a GP whose
                        # compatibility niche simply is not selected in this global scan.
                        "affinity": 100.0,
                    }
                )

            profile_parent_max: dict[int, float | None] = {index: None for index in range(len(veterans))}
            profile_gp_max: dict[int, float | None] = {index: None for index in range(len(veterans))}

            for ace in aces:
                ace_chara = int(ace.get("chara_id") or 0)
                parent_scores: dict[int, float | None] = {}
                gp_scores: dict[int, float] = {}
                for veteran_index, veteran in enumerate(veterans):
                    parent_score: float | None
                    if int(veteran.get("chara_id") or 0) == ace_chara:
                        parent_score = None
                    else:
                        affinity_key = (ace_chara, veteran_index)
                        affinity = affinity_cache.get(affinity_key)
                        if affinity is None:
                            affinity = _branch_affinity(
                                resolver, ace_chara, veteran, g1_bonus_value
                            )
                            affinity_cache[affinity_key] = affinity
                        parent_components = dict(parent_static[veteran_index])
                        parent_inheritance_affinities = _branch_inheritance_affinities(
                            resolver, ace_chara, veteran, g1_bonus_value
                        )
                        parent_white, _ = _white_score(
                            _lineage_members(veteran),
                            weight_lookup,
                            config,
                            "parent_branch",
                            inheritance_affinities=parent_inheritance_affinities,
                            race_skill_map=race_skills,
                        )
                        parent_components["white_skill"] = parent_white
                        parent_pink, parent_pink_detail = _pink_score(
                            _lineage_members(veteran),
                            ace,
                            context.surface,
                            context.distance,
                            context.style,
                            config,
                            mode="parent_branch",
                            inheritance_affinities=parent_inheritance_affinities,
                        )
                        parent_components["pink"] = parent_pink
                        parent_components["distance_s"] = float(parent_pink_detail["distance_s"]["score"])
                        parent_components["pink_other"] = float(parent_pink_detail["pink_other"]["score"])
                        parent_components["affinity"] = _affinity_score(
                            float(affinity["total"]), branch_thresholds
                        )
                        parent_score = _weighted_total(parent_components, parent_weights)
                        _update_best(records[veteran_index], "parent", parent_score, context, ace)
                        current_max = profile_parent_max[veteran_index]
                        if current_max is None or parent_score > current_max:
                            profile_parent_max[veteran_index] = parent_score

                    gp_components = dict(gp_static[veteran_index])
                    gp_pink, _ = _future_grandparent_pink_score(
                        [(veteran, "grandparent", "candidate")],
                        ace,
                        context.surface,
                        context.distance,
                        context.style,
                        config,
                    )
                    gp_components["pink"] = gp_pink
                    gp_score = _weighted_total(gp_components, grandparent_weights)
                    _update_best(records[veteran_index], "grandparent", gp_score, context, ace)
                    current_gp_max = profile_gp_max[veteran_index]
                    if current_gp_max is None or gp_score > current_gp_max:
                        profile_gp_max[veteran_index] = gp_score

                    parent_scores[veteran_index] = parent_score
                    gp_scores[veteran_index] = gp_score

                ace_parent_percentiles = _rank_percentiles(parent_scores)
                ace_gp_percentiles = _rank_percentiles(gp_scores)
                ace_parent_quality = _profile_quality_metrics(
                    parent_scores, ace_parent_percentiles,
                    absolute_floor=competitive_score_floor,
                    absolute_weight=utility_absolute_weight,
                    leader_weight=utility_leader_weight,
                    percentile_weight=utility_percentile_weight,
                )
                ace_gp_quality = _profile_quality_metrics(
                    gp_scores, ace_gp_percentiles,
                    absolute_floor=competitive_score_floor,
                    absolute_weight=utility_absolute_weight,
                    leader_weight=utility_leader_weight,
                    percentile_weight=utility_percentile_weight,
                )
                for group_indices in groups.values():
                    if len(group_indices) < 2:
                        continue
                    _update_group_dominance_for_scores(
                        group_indices,
                        relations,
                        parent_scores,
                        gp_scores,
                        ace_parent_quality,
                        ace_gp_quality,
                        competitive_score_floor=competitive_score_floor,
                        competitive_utility_floor=competitive_utility_floor,
                        minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
                        dominance_tolerance=dominance_tolerance,
                    )

            parent_percentiles = _rank_percentiles(profile_parent_max)
            gp_percentiles = _rank_percentiles(profile_gp_max)
            parent_quality = _profile_quality_metrics(
                profile_parent_max, parent_percentiles,
                absolute_floor=competitive_score_floor,
                absolute_weight=utility_absolute_weight,
                leader_weight=utility_leader_weight,
                percentile_weight=utility_percentile_weight,
            )
            gp_quality = _profile_quality_metrics(
                profile_gp_max, gp_percentiles,
                absolute_floor=competitive_score_floor,
                absolute_weight=utility_absolute_weight,
                leader_weight=utility_leader_weight,
                percentile_weight=utility_percentile_weight,
            )
            for veteran_index, record in enumerate(records):
                parent_score = profile_parent_max[veteran_index]
                gp_score = profile_gp_max[veteran_index]
                if parent_score is not None:
                    record["_parent_profiles"].append(
                        {
                            "context_key": context.key,
                            "profile": context.label,
                            "score": round(parent_score, 6),
                            "percentile": round(parent_percentiles.get(veteran_index, 100.0), 4),
                            "utility": round(parent_quality.get(veteran_index, {}).get("utility", 0.0), 6),
                            "relative_to_leader": round(parent_quality.get(veteran_index, {}).get("relative_to_leader", 0.0), 6),
                            "score_gap_to_leader": round(parent_quality.get(veteran_index, {}).get("score_gap_to_leader", 0.0), 6),
                            "leader_score": round(parent_quality.get(veteran_index, {}).get("leader_score", 0.0), 6),
                            "course_key": context.course_key,
                            "style": context.style,
                        }
                    )
                    record["_best_parent_percentile"] = min(
                        float(record["_best_parent_percentile"]),
                        parent_percentiles.get(veteran_index, 100.0),
                    )
                if gp_score is not None:
                    record["_grandparent_profiles"].append(
                        {
                            "context_key": context.key,
                            "profile": context.label,
                            "score": round(gp_score, 6),
                            "percentile": round(gp_percentiles.get(veteran_index, 100.0), 4),
                            "utility": round(gp_quality.get(veteran_index, {}).get("utility", 0.0), 6),
                            "relative_to_leader": round(gp_quality.get(veteran_index, {}).get("relative_to_leader", 0.0), 6),
                            "score_gap_to_leader": round(gp_quality.get(veteran_index, {}).get("score_gap_to_leader", 0.0), 6),
                            "leader_score": round(gp_quality.get(veteran_index, {}).get("leader_score", 0.0), 6),
                            "course_key": context.course_key,
                            "style": context.style,
                        }
                    )
                    record["_best_grandparent_percentile"] = min(
                        float(record["_best_grandparent_percentile"]),
                        gp_percentiles.get(veteran_index, 100.0),
                    )

            if context_index % 8 == 0 or context_index == len(contexts):
                log(f"Profils Transfer Helper : {context_index}/{len(contexts)}")
    finally:
        resolver.close()

    classify_transfer_records(
        records,
        relations,
        elite_utility_floor=elite_utility_floor,
        competitive_utility_floor=competitive_utility_floor,
        competitive_score_floor=competitive_score_floor,
        minimum_absolute_floor_ratio=minimum_absolute_floor_ratio,
        minimum_competitive_contexts=minimum_competitive_contexts,
        minimum_distinct_profiles=minimum_distinct_profiles,
        dominance_mean_margin=dominance_mean_margin,
    )

    status_order = {"safe_transfer": 0, "review": 1, "likely_keep": 2, "keep": 3}
    for record in records:
        record["best_parent_score"] = round(float(record.pop("_best_parent_score")), 4)
        record["best_grandparent_score"] = round(float(record.pop("_best_grandparent_score")), 4)
        record["best_parent_percentile"] = round(float(record.pop("_best_parent_percentile")), 4)
        record["best_grandparent_percentile"] = round(float(record.pop("_best_grandparent_percentile")), 4)
        record["best_parent_context"] = record.pop("_best_parent_context", None)
        record["best_grandparent_context"] = record.pop("_best_grandparent_context", None)
        parent_profiles = record.pop("_parent_profiles")
        grandparent_profiles = record.pop("_grandparent_profiles")
        record["top_parent_profiles"] = sorted(
            parent_profiles,
            key=lambda item: (item["score"], -item["percentile"]),
            reverse=True,
        )[:8]
        record["top_grandparent_profiles"] = sorted(
            grandparent_profiles,
            key=lambda item: (item["score"], -item["percentile"]),
            reverse=True,
        )[:8]

    records.sort(
        key=lambda record: (
            status_order.get(str(record.get("status")), 99),
            -float(((record.get("dominated_by") or {}).get("mean_score_lead")) or 0.0),
            float(record.get("best_parent_score") or 0.0)
            + float(record.get("best_grandparent_score") or 0.0),
        )
    )

    counts = Counter(str(record.get("status")) for record in records)
    generated_at = datetime.now(timezone.utc).isoformat()
    # Do not include the full pairwise matrix in the normal report: it is large and
    # the selected dominator already carries the useful evidence.
    payload = {
        "metadata": {
            "format_version": 2,
            "generated_at_utc": generated_at,
            "purpose": "Selective helper for identifying redundant local veterans before transferring them in game.",
            "source_master": {"filename": master.name, "sha256": _sha256(master)},
            "source_veterans": {"filename": linked_path.name, "sha256": _sha256(linked_path)},
            "source_skill_weights": {"filename": weights_path.name, "sha256": _sha256(weights_path)},
            "source_scoring_config": {"filename": config_path.name, "sha256": _sha256(config_path)},
            "veteran_count": len(veterans),
            "profile_context_count": len(contexts),
            "generic_profile_count": sum(context.course_key is None for context in contexts),
            "course_profile_count": sum(context.course_key is not None for context in contexts),
            "ace_variant_counts": {
                "/".join(key): len(value) for key, value in sorted(ace_cache.items())
            },
            "status_counts": dict(sorted(counts.items())),
            "safety_notes": [
                "The helper never modifies data.json and never transfers a veteran automatically.",
                "Safe transfer requires one same-card/same-unique replacement that is not worse in every globally viable parent or grandparent context for that card, remains at least as good for G1 pair support, and clears the configured average lead.",
                "A context is ignored for same-card dominance when every copy of that card is globally outclassed there; being the least-bad copy in a non-viable niche does not force a keep.",
                "Keep requires elite performance or repeated competitiveness across several contexts and course profiles. A single narrow niche is classified as likely keep.",
                "Review means no meaningful role was detected under the configured thresholds; it is not an automatic deletion recommendation.",
                "Grandparent scores use an optimistic constant affinity ceiling so a character-specific compatibility niche is not discarded merely because no target was selected.",
                "Alternate costumes are never treated as interchangeable, even when they share the same base character.",
            ],
        },
        "settings": settings,
        "contexts": [context.__dict__ for context in contexts],
        "records": records,
    }

    report_path = destination / "transfer_helper_report.json"
    csv_path = destination / "transfer_helper_candidates.csv"
    summary_path = destination / "transfer_helper_summary.txt"
    _write_json(report_path, payload)

    csv_rows = []
    for record in records:
        dominated_by = record.get("dominated_by") or {}
        csv_rows.append(
            {
                "status": record.get("status"),
                "reason": record.get("reason_code"),
                "trained_chara_id": record.get("trained_chara_id"),
                "card_id": record.get("card_id"),
                "uma_name": record.get("uma_name"),
                "card_name": record.get("card_name"),
                "rank": record.get("rank"),
                "rank_score": record.get("rank_score"),
                "speed": (record.get("stats") or {}).get("speed"),
                "stamina": (record.get("stats") or {}).get("stamina"),
                "power": (record.get("stats") or {}).get("power"),
                "guts": (record.get("stats") or {}).get("guts"),
                "wisdom": (record.get("stats") or {}).get("wiz"),
                "grandparent_1": record.get("grandparent_1"),
                "grandparent_2": record.get("grandparent_2"),
                "same_card_copies": record.get("same_card_copy_count"),
                "referenced_by": record.get("referenced_by_local_veterans"),
                "best_parent_score": record.get("best_parent_score"),
                "best_parent_percentile": record.get("best_parent_percentile"),
                "best_parent_profile": ((record.get("best_parent_context") or {}).get("profile")),
                "best_grandparent_score": record.get("best_grandparent_score"),
                "best_grandparent_percentile": record.get("best_grandparent_percentile"),
                "best_grandparent_profile": ((record.get("best_grandparent_context") or {}).get("profile")),
                "parent_competitive_contexts": ((record.get("parent_evidence") or {}).get("competitive_context_count")),
                "parent_distinct_profiles": ((record.get("parent_evidence") or {}).get("competitive_distinct_profile_count")),
                "grandparent_competitive_contexts": ((record.get("grandparent_evidence") or {}).get("competitive_context_count")),
                "grandparent_distinct_profiles": ((record.get("grandparent_evidence") or {}).get("competitive_distinct_profile_count")),
                "dominated_by_id": dominated_by.get("trained_chara_id"),
                "dominated_by": dominated_by.get("card_name"),
                "mean_score_lead": dominated_by.get("mean_score_lead"),
                "worst_context_delta": dominated_by.get("worst_context_delta"),
                "viable_parent_comparisons": dominated_by.get("viable_parent_comparisons"),
                "viable_grandparent_comparisons": dominated_by.get("viable_grandparent_comparisons"),
            }
        )
    _write_csv(
        csv_path,
        csv_rows,
        [
            "status",
            "reason",
            "trained_chara_id",
            "card_id",
            "uma_name",
            "card_name",
            "rank",
            "rank_score",
            "speed",
            "stamina",
            "power",
            "guts",
            "wisdom",
            "grandparent_1",
            "grandparent_2",
            "same_card_copies",
            "referenced_by",
            "best_parent_score",
            "best_parent_percentile",
            "best_parent_profile",
            "best_grandparent_score",
            "best_grandparent_percentile",
            "best_grandparent_profile",
            "parent_competitive_contexts",
            "parent_distinct_profiles",
            "grandparent_competitive_contexts",
            "grandparent_distinct_profiles",
            "dominated_by_id",
            "dominated_by",
            "mean_score_lead",
            "worst_context_delta",
            "viable_parent_comparisons",
            "viable_grandparent_comparisons",
        ],
    )

    summary_lines = [
        "Uma Legacy Linker — Transfer Helper",
        "=" * 38,
        f"Generated: {generated_at}",
        f"Veterans analysed: {len(veterans)}",
        f"Profile/category contexts: {len(contexts)}",
        f"Safe transfer: {counts.get('safe_transfer', 0)}",
        f"Review: {counts.get('review', 0)}",
        f"Likely keep: {counts.get('likely_keep', 0)}",
        f"Keep: {counts.get('keep', 0)}",
        "",
        "Safe-transfer candidates",
        "------------------------",
    ]
    safe_records = [record for record in records if record.get("status") == "safe_transfer"]
    if not safe_records:
        summary_lines.append("None.")
    for record in safe_records:
        replacement = record.get("dominated_by") or {}
        summary_lines.append(
            f"- {record.get('card_name')} [{record.get('trained_chara_id')}] -> "
            f"{replacement.get('card_name')} [{replacement.get('trained_chara_id')}] "
            f"(mean lead {replacement.get('mean_score_lead')})"
        )
    summary_lines.extend(
        [
            "",
            "Important: review candidates are not automatic transfer recommendations. Inspect their detailed JSON profile before deleting anything in game.",
        ]
    )
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    log(f"Transfer Helper terminé : {report_path}")
    return TransferHelperResult(
        report_json_path=report_path,
        candidates_csv_path=csv_path,
        summary_txt_path=summary_path,
        safe_transfer_count=counts.get("safe_transfer", 0),
        review_count=counts.get("review", 0),
        likely_keep_count=counts.get("likely_keep", 0),
        keep_count=counts.get("keep", 0),
        records=tuple(records),
        settings=settings,
    )

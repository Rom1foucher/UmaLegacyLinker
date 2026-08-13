from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from g1_race_planning import build_pair_g1_diagnostic
from parent_optimizer import (
    APTITUDE_LABELS,
    DISTANCE_FACTOR_NAMES,
    SURFACE_FACTOR_NAMES,
    _initial_aptitude_rank,
    _pink_score,
)
from loop_models import (
    BRANCH_TYPES,
    LOOP_VERDICTS,
    LoopCarrier,
    LoopDraftTransition,
    LoopProject,
    LoopRunResult,
    LoopSkillTarget,
    LoopTransition,
    new_transition,
    utc_now,
)

GENERATION_MODELS: dict[str, tuple[float, float]] = {
    "normal": (0.20, 0.025),
    "circle": (0.25, 0.025),
    "gold": (0.40, 0.05),
}

STAR_DISTRIBUTIONS: dict[str, dict[int, float]] = {
    "below_ss": {1: 0.45, 2: 0.50, 3: 0.05},
    "ss_to_ue_plus": {1: 0.20, 2: 0.70, 3: 0.10},
    "ue_plus": {1: 0.175, 2: 0.70, 3: 0.125},
}


class LoopEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoopFactorOption:
    key: str
    name: str
    factor_group_id: int | None
    catalog_key: str
    skill_id: int | None = None


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value.casefold()).strip("_")


def factor_key(factor: dict[str, Any]) -> str:
    factor_type = str(factor.get("type") or "white_skill")
    group_id = _integer(factor.get("factor_group_id"))
    if group_id is not None and group_id > 0:
        return f"{factor_type}:group:{group_id}"
    skill_id = _integer(factor.get("skill_id"))
    if skill_id is not None and skill_id > 0:
        return f"{factor_type}:skill:{skill_id}"
    name = str(factor.get("name") or "").strip()
    return f"{factor_type}:name:{name.casefold()}"


def _factor_list(member: object, factor_type: str = "white_skill") -> list[dict[str, Any]]:
    if not isinstance(member, dict):
        return []
    factors = (member.get("factors") or {}).get("by_type", {}).get(factor_type)
    if not isinstance(factors, list):
        factors = [
            factor
            for factor in (member.get("sparks") or (member.get("factors") or {}).get("all") or [])
            if isinstance(factor, dict) and str(factor.get("type") or "") == factor_type
        ]
    return [factor for factor in factors if isinstance(factor, dict)]


def target_factor(target: LoopSkillTarget, member: object) -> dict[str, Any] | None:
    factors = _factor_list(member)
    for factor in factors:
        if factor_key(factor) == target.key:
            return factor
        if target.factor_group_id is not None and _integer(
            factor.get("factor_group_id")
        ) == target.factor_group_id:
            return factor
    # Name matching is intentionally a last-resort compatibility path for old
    # linked exports that did not retain factor-group IDs.  A present but
    # different group ID is authoritative and must never collapse by name.
    expected = str(target.name or "").strip().casefold()
    return next(
        (
            factor
            for factor in factors
            if _integer(factor.get("factor_group_id")) is None
            if str(factor.get("name") or "").strip().casefold() == expected
        ),
        None,
    )


def _member_rank_score(member: dict[str, Any]) -> float:
    try:
        return max(0.0, float(member.get("rank_score") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _member_g1_count(member: dict[str, Any]) -> int:
    try:
        explicit = int(member.get("g1_count") or 0)
    except (TypeError, ValueError):
        explicit = 0
    if explicit > 0:
        return explicit
    wins = (member.get("g1_wins") or {}).get("names") if isinstance(member, dict) else []
    return len(wins) if isinstance(wins, list) else 0


def _candidate_target_metrics(
    member: dict[str, Any],
    targets: list[LoopSkillTarget],
) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    for target in targets:
        factor = target_factor(target, member)
        if factor is None:
            continue
        hits.append(
            {
                "key": target.key,
                "name": target.name,
                "policy": target.policy,
                "stars": max(0, _integer(factor.get("stars")) or 0),
            }
        )
    return {
        "hits": hits,
        "direct_hits": len(hits),
        "static_hits": sum(item["policy"] == "static" for item in hits),
        "star_sum": sum(int(item["stars"]) for item in hits),
        "weighted_hits": sum(
            target.weight
            for target in targets
            if any(item["key"] == target.key for item in hits)
        ),
    }


def rank_parent_candidates(
    veterans: Iterable[dict[str, Any]],
    targets: Iterable[LoopSkillTarget],
    *,
    exclude_chara_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return a deterministic, target-oriented ranking for local parent choices.

    This is deliberately a recommendation score, not a game probability.  With
    targets it rewards exact direct-factor coverage (70%), static coverage (20%)
    and the stars on those factors (10%).  Without targets it falls back to the
    linked export's rank score so the selectors are still useful before the first
    target is added.
    """

    selected_targets = list(targets)
    collection = [veteran for veteran in veterans if isinstance(veteran, dict)]
    collection_max_score = max(
        (_member_rank_score(veteran) for veteran in collection),
        default=0.0,
    )
    static_count = sum(target.is_static for target in selected_targets)
    total_weight = sum(max(0.0, target.weight) for target in selected_targets) or 1.0
    rows: list[dict[str, Any]] = []
    excluded = _integer(exclude_chara_id)
    for veteran in collection:
        trained_id = _integer(veteran.get("trained_chara_id"))
        chara_id = _integer(veteran.get("chara_id"))
        if trained_id is None or trained_id <= 0:
            continue
        if excluded is not None and chara_id == excluded:
            continue
        metrics = _candidate_target_metrics(veteran, selected_targets)
        rank_score = _member_rank_score(veteran)
        if selected_targets:
            coverage_ratio = metrics["weighted_hits"] / total_weight
            static_ratio = (
                metrics["static_hits"] / static_count if static_count else coverage_ratio
            )
            quality_reference = max(1, metrics["direct_hits"] * 3)
            quality_ratio = min(1.0, metrics["star_sum"] / quality_reference)
            heuristic_score = 70.0 * coverage_ratio
            heuristic_score += 20.0 * static_ratio
            heuristic_score += 10.0 * quality_ratio
        else:
            heuristic_score = (
                100.0 * rank_score / collection_max_score
                if collection_max_score > 0.0
                else min(100.0, 2.0 * _member_g1_count(veteran))
            )
        rows.append(
            {
                "veteran": veteran,
                "trained_chara_id": trained_id,
                "chara_id": chara_id,
                "name": _member_name(veteran),
                "rank": str(veteran.get("rank") or "—"),
                "rank_score": round(rank_score, 4),
                "heuristic_score": round(max(0.0, min(100.0, heuristic_score)), 4),
                "target_count": len(selected_targets),
                "direct_hits": int(metrics["direct_hits"]),
                "static_hits": int(metrics["static_hits"]),
                "static_target_count": static_count,
                "weighted_hits": round(float(metrics["weighted_hits"]), 4),
                "target_star_sum": int(metrics["star_sum"]),
                "target_names": [item["name"] for item in metrics["hits"]],
                "g1_count": _member_g1_count(veteran),
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["heuristic_score"]),
            -int(row["static_hits"]),
            -float(row["weighted_hits"]),
            -int(row["target_star_sum"]),
            -float(row["rank_score"]),
            str(row["name"]).casefold(),
            int(row["trained_chara_id"]),
        )
    )
    for position, row in enumerate(rows, start=1):
        row["rank_position"] = position
    if limit is not None:
        return rows[: max(0, int(limit))]
    return rows


def future_parent_training_aptitudes(
    trainee: dict[str, Any],
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
) -> dict[str, Any]:
    """Apply the selected six-member Pink lineage to career-training ranks.

    Independent Training only needs surface and distance.  Running style is
    still scored for the target profile, but deliberately does not enter the
    G1 win-probability cutoff.
    """

    base = copy.deepcopy(trainee.get("training_aptitudes") or {})
    result: dict[str, Any] = {
        "surface": dict(base.get("surface") or {}),
        "distance": dict(base.get("distance") or {}),
    }
    factor_names = {
        "surface": SURFACE_FACTOR_NAMES,
        "distance": DISTANCE_FACTOR_NAMES,
    }
    members = [member for _role, member in branch_slots(parent_1, parent_2) if member]
    for dimension, names in factor_names.items():
        for key, factor_name in names.items():
            payload = result[dimension].get(key)
            if not isinstance(payload, dict):
                continue
            try:
                base_rank = int(
                    payload.get("base_rank", payload.get("initial_rank", 0)) or 0
                )
            except (TypeError, ValueError):
                continue
            total_stars = sum(
                max(0, _integer(factor.get("stars")) or 0)
                for member in members
                for factor in _factor_list(member, "red_aptitude")
                if str(factor.get("name") or "") == factor_name
            )
            initial_rank = _initial_aptitude_rank(base_rank, total_stars)
            result[dimension][key] = {
                **payload,
                "factor_name": factor_name,
                "base_rank": base_rank,
                "base_rank_label": APTITUDE_LABELS.get(base_rank, str(base_rank)),
                "inherited_stars": total_stars,
                "initial_rank": initial_rank,
                "initial_rank_label": APTITUDE_LABELS.get(initial_rank, str(initial_rank)),
            }
    return result


def _pair_aptitude_metrics(
    slots: list[tuple[str, dict[str, Any] | None]],
    trainee: dict[str, Any] | None,
    *,
    surface: str | None,
    distance: str | None,
    style: str | None,
    aptitude_config: dict[str, Any] | None,
) -> dict[str, Any]:
    if not trainee or not aptitude_config or not surface or not distance or not style:
        return {"available": False, "score": None}
    target_aptitudes = trainee.get("target_aptitudes")
    if not isinstance(target_aptitudes, dict) or not all(
        isinstance(target_aptitudes.get(key), dict)
        for key in ("surface", "distance", "style")
    ):
        return {"available": False, "score": None}
    members = [
        (
            member,
            "parent" if role in {"p1", "p2"} else "grandparent",
            role,
        )
        for role, member in slots
        if isinstance(member, dict)
    ]
    try:
        score, detail = _pink_score(
            members,
            trainee,
            surface,
            distance,
            style,
            aptitude_config,
            mode="parent_pair",
        )
    except (KeyError, TypeError, ValueError):
        return {"available": False, "score": None}
    dimensions = detail.get("dimensions") or {}

    def compact(key: str) -> dict[str, Any]:
        payload = dimensions.get(key) or {}
        return {
            "target": payload.get("target"),
            "base_rank": payload.get("base_rank"),
            "base_rank_label": payload.get("base_rank_label"),
            "initial_rank": payload.get("initial_rank"),
            "initial_rank_label": payload.get("initial_rank_label"),
            "stars": int(payload.get("total_stars") or 0),
            "probability_a": payload.get("probability_reach_a"),
            "probability_s": payload.get("probability_reach_s"),
            "score": payload.get("score"),
        }

    return {
        "available": True,
        "score": round(max(0.0, min(100.0, float(score))), 4),
        "surface": compact("surface"),
        "distance": compact("distance"),
        "style": compact("style"),
        "dimension_weights": copy.deepcopy(detail.get("dimension_weights") or {}),
        "model": "canonical_probability_aware_pink",
    }


def rank_parent_pairs(
    veterans: Iterable[dict[str, Any]],
    targets: Iterable[LoopSkillTarget],
    *,
    trainee: dict[str, Any] | None = None,
    surface: str | None = None,
    distance: str | None = None,
    style: str | None = None,
    aptitude_config: dict[str, Any] | None = None,
    candidate_limit: int = 40,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Rank practical local parent duos before the user starts a run.

    The White subscore uses the same exact factor matcher as transition analysis,
    counting the two parents and their four visible grandparents (six slots).
    When a complete MDB context is supplied, the displayed recommendation is
    80% White subscore plus 20% canonical probability-aware Pink aptitude score.
    Only the best candidate pool is paired to keep the UI responsive on large
    collections; the final transition analysis remains authoritative.
    """

    selected_targets = list(targets)
    trainee_chara = _integer((trainee or {}).get("chara_id"))
    candidates = rank_parent_candidates(
        veterans,
        selected_targets,
        exclude_chara_id=trainee_chara,
        limit=max(2, int(candidate_limit)),
    )
    static_count = sum(target.is_static for target in selected_targets)
    total_weight = sum(max(0.0, target.weight) for target in selected_targets) or 1.0
    rows: list[dict[str, Any]] = []
    for left, right in combinations(candidates, 2):
        left_member = left["veteran"]
        right_member = right["veteran"]
        if int(left["trained_chara_id"]) == int(right["trained_chara_id"]):
            continue
        left_chara = _integer(left_member.get("chara_id"))
        right_chara = _integer(right_member.get("chara_id"))
        if left_chara is not None and left_chara == right_chara:
            continue
        slots = branch_slots(left_member, right_member)
        aptitude = _pair_aptitude_metrics(
            slots,
            trainee,
            surface=surface,
            distance=distance,
            style=style,
            aptitude_config=aptitude_config,
        )
        coverage_by_target: list[dict[str, Any]] = []
        weighted_coverage = 0.0
        direct_coverage = 0
        static_direct_coverage = 0
        target_star_sum = 0
        for target in selected_targets:
            matched = [
                role for role, member in slots if target_factor(target, member) is not None
            ]
            direct_roles = [role for role in matched if role in {"p1", "p2"}]
            stars = sum(
                max(
                    0,
                    _integer(
                        (target_factor(target, member) or {}).get("stars")
                    )
                    or 0,
                )
                for _role, member in slots
                if target_factor(target, member) is not None
            )
            weighted_coverage += max(0.0, target.weight) * len(matched)
            direct_coverage += len(direct_roles)
            static_direct_coverage += len(direct_roles) if target.is_static else 0
            target_star_sum += stars
            coverage_by_target.append(
                {
                    "key": target.key,
                    "name": target.name,
                    "coverage": len(matched),
                    "direct_coverage": len(direct_roles),
                    "roles": matched,
                    "stars": stars,
                }
            )
        if selected_targets:
            coverage_ratio = weighted_coverage / (total_weight * 6.0)
            static_ratio = (
                static_direct_coverage / (static_count * 2.0)
                if static_count
                else coverage_ratio
            )
            quality_reference = max(1, len(selected_targets) * 6 * 3)
            quality_ratio = min(1.0, target_star_sum / quality_reference)
            white_score = 70.0 * coverage_ratio + 20.0 * static_ratio + 10.0 * quality_ratio
        else:
            white_score = (
                float(left["heuristic_score"]) + float(right["heuristic_score"])
            ) / 2.0
        aptitude_score = aptitude.get("score")
        heuristic_score = (
            0.80 * white_score + 0.20 * float(aptitude_score)
            if aptitude_score is not None
            else white_score
        )
        rows.append(
            {
                "parent_1": left_member,
                "parent_2": right_member,
                "parent_1_trained_id": int(left["trained_chara_id"]),
                "parent_2_trained_id": int(right["trained_chara_id"]),
                "parent_1_name": left["name"],
                "parent_2_name": right["name"],
                "parent_1_score": float(left["heuristic_score"]),
                "parent_2_score": float(right["heuristic_score"]),
                "parent_1_rank": left["rank"],
                "parent_2_rank": right["rank"],
                "parent_1_in_game_score": float(left["rank_score"]),
                "parent_2_in_game_score": float(right["rank_score"]),
                "white_score": round(max(0.0, min(100.0, white_score)), 4),
                "aptitude": aptitude,
                "aptitude_score": aptitude_score,
                "heuristic_score": round(max(0.0, min(100.0, heuristic_score)), 4),
                "target_count": len(selected_targets),
                "lineage_coverage": sum(item["coverage"] for item in coverage_by_target),
                "lineage_coverage_max": len(selected_targets) * 6,
                "direct_coverage": direct_coverage,
                "static_direct_coverage": static_direct_coverage,
                "static_target_count": static_count,
                "target_star_sum": target_star_sum,
                "coverage_by_target": coverage_by_target,
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row["heuristic_score"]),
            -int(row["lineage_coverage"]),
            -int(row["static_direct_coverage"]),
            -int(row["target_star_sum"]),
            str(row["parent_1_name"]).casefold(),
            str(row["parent_2_name"]).casefold(),
            int(row["parent_1_trained_id"]),
            int(row["parent_2_trained_id"]),
        )
    )
    for position, row in enumerate(rows, start=1):
        row["rank_position"] = position
    if limit is not None:
        return rows[: max(0, int(limit))]
    return rows


def load_linked_veterans(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    resolved = Path(path).expanduser()
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise LoopEngineError(
            "Lance d’abord la liaison de la collection pour utiliser le Loop Workshop."
        ) from exc
    except json.JSONDecodeError as exc:
        raise LoopEngineError(
            f"Le fichier de vétérans liés est invalide : {resolved.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise LoopEngineError("Le fichier de vétérans liés doit contenir un objet JSON.")
    veterans = [
        member
        for member in payload.get("veterans") or []
        if isinstance(member, dict)
    ]
    if not veterans:
        raise LoopEngineError("Aucun vétéran lié n’est disponible pour le looping.")
    return payload, veterans


def load_skill_catalog(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        return {}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_target_options(
    veterans: Iterable[dict[str, Any]],
    skill_catalog: dict[str, Any] | None = None,
) -> list[LoopFactorOption]:
    options: dict[str, LoopFactorOption] = {}
    for group in (skill_catalog or {}).get("white_skill_spark_groups") or []:
        if not isinstance(group, dict):
            continue
        group_id = _integer(group.get("factor_group_id"))
        name = str(group.get("spark_name") or "").strip()
        if group_id is None or group_id <= 0 or not name:
            continue
        key = f"white_skill:group:{group_id}"
        options[key] = LoopFactorOption(
            key=key,
            name=name,
            factor_group_id=group_id,
            catalog_key=str(group.get("catalog_key") or _slug(name)),
            skill_id=(
                _integer(group.get("skill_id"))
                or _integer(group.get("source_skill_id"))
                or _integer(group.get("base_skill_id"))
            ),
        )
    catalog_keys_by_name = {
        option.name.casefold(): option.key for option in options.values()
    }
    for veteran in veterans:
        members = [veteran]
        lineage = veteran.get("when_used_as_parent") or {}
        if isinstance(lineage, dict):
            members.extend(
                lineage.get(key)
                for key in ("grandparent_1", "grandparent_2")
            )
        for member in members:
            for factor in _factor_list(member):
                name = str(factor.get("name") or "").strip()
                if not name:
                    continue
                key = factor_key(factor)
                if _integer(factor.get("factor_group_id")) is None:
                    catalog_key = catalog_keys_by_name.get(name.casefold())
                    if catalog_key is not None:
                        continue
                options.setdefault(
                    key,
                    LoopFactorOption(
                        key=key,
                        name=name,
                        factor_group_id=_integer(factor.get("factor_group_id")),
                        catalog_key=_slug(name),
                        skill_id=_integer(factor.get("skill_id")),
                    ),
                )
    return sorted(options.values(), key=lambda option: option.name.casefold())


def branch_slots(
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
) -> list[tuple[str, dict[str, Any] | None]]:
    result: list[tuple[str, dict[str, Any] | None]] = []
    for prefix, parent in (("p1", parent_1), ("p2", parent_2)):
        result.append((prefix, parent))
        lineage = parent.get("when_used_as_parent") or {}
        if not isinstance(lineage, dict):
            lineage = {}
        result.extend(
            (
                (f"{prefix}-1", lineage.get("grandparent_1")),
                (f"{prefix}-2", lineage.get("grandparent_2")),
            )
        )
    return result


def generation_probability(learned_form: str, lineage_copies: int) -> float:
    try:
        base, per_copy = GENERATION_MODELS[learned_form]
    except KeyError as exc:
        raise LoopEngineError(f"Forme de compétence inconnue : {learned_form}") from exc
    copies = max(0, min(6, int(lineage_copies)))
    return min(1.0, base + per_copy * copies)


def _identity(member: dict[str, Any]) -> dict[str, Any]:
    return {
        key: member.get(key)
        for key in (
            "trained_chara_id",
            "card_id",
            "chara_id",
            "uma_name",
            "card_name",
            "rank",
            "rank_score",
        )
        if member.get(key) is not None
    }


def member_fingerprint(member: object) -> str | None:
    """Fingerprint a frozen lineage member without relying on local IDs.

    umadump currently leaves succession-trained IDs at zero.  Card identity,
    exact factors/stars and G1 wins still provide a deterministic fallback for
    confirming that an extracted descendant used the two planned parents.
    """

    if not isinstance(member, dict) or not member:
        return None
    factors = []
    raw_factors = member.get("sparks")
    if not isinstance(raw_factors, list):
        raw_factors = list((member.get("factors") or {}).get("all") or [])
    for factor in raw_factors:
        if not isinstance(factor, dict):
            continue
        factors.append(
            {
                "type": str(factor.get("type") or "other"),
                "group": _integer(factor.get("factor_group_id")),
                "id": _integer(factor.get("factor_id")),
                "name": str(factor.get("name") or "").strip().casefold(),
                "stars": max(0, _integer(factor.get("stars")) or 0),
            }
        )
    payload = {
        "card_id": _integer(member.get("card_id")),
        "chara_id": _integer(member.get("chara_id")),
        "factors": sorted(
            factors,
            key=lambda factor: (
                factor["type"],
                factor["group"] or 0,
                factor["id"] or 0,
                factor["name"],
                factor["stars"],
            ),
        ),
        "g1": sorted(
            str(name).strip().casefold()
            for name in ((member.get("g1_wins") or {}).get("names") or [])
            if str(name).strip()
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _member_name(member: dict[str, Any]) -> str:
    return str(member.get("card_name") or member.get("uma_name") or "Vétéran")


def _validate_transition_members(
    trainee: dict[str, Any],
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
) -> None:
    parent_1_id = _integer(parent_1.get("trained_chara_id"))
    parent_2_id = _integer(parent_2.get("trained_chara_id"))
    if parent_1_id is None or parent_2_id is None:
        raise LoopEngineError("Les deux parents doivent être des vétérans locaux identifiables.")
    if parent_1_id == parent_2_id:
        raise LoopEngineError("Sélectionne deux vétérans parents différents.")
    chara_1 = _integer(parent_1.get("chara_id"))
    chara_2 = _integer(parent_2.get("chara_id"))
    if chara_1 is not None and chara_1 == chara_2:
        raise LoopEngineError("Les deux parents directs doivent être des personnages différents.")
    trainee_chara = _integer(trainee.get("chara_id"))
    if trainee_chara is not None and trainee_chara in {chara_1, chara_2}:
        raise LoopEngineError("Le trainee ne peut pas être son propre parent direct.")


def _normalised_g1_signature(names: Iterable[str]) -> list[str]:
    return list(
        dict.fromkeys(str(name).strip() for name in names if str(name).strip())
    )


def analyze_transition(
    *,
    trainee: dict[str, Any],
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    targets: Iterable[LoopSkillTarget],
    quality_band: str = "ss_to_ue_plus",
    race_budget: int = 28,
    g1_signature: Iterable[str] = (),
    g1_win_probability_cutoff: float = 0.60,
) -> dict[str, Any]:
    _validate_transition_members(trainee, parent_1, parent_2)
    selected_targets = list(targets)
    if not selected_targets:
        raise LoopEngineError("Ajoute au moins une White Skill cible au projet.")
    if quality_band not in STAR_DISTRIBUTIONS:
        raise LoopEngineError(f"Bande de qualité inconnue : {quality_band}")

    slots = branch_slots(parent_1, parent_2)
    resolved_slot_count = sum(isinstance(member, dict) for _role, member in slots)
    distribution = STAR_DISTRIBUTIONS[quality_band]
    target_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    static_count = sum(target.is_static for target in selected_targets)
    if static_count > 2:
        warnings.append(
            "Plus de deux cibles statiques rendent la réussite simultanée très improbable."
        )
    if resolved_slot_count < 6:
        warnings.append(
            "La lignée est incomplète : les probabilités de génération sont des bornes basses."
        )

    for target in selected_targets:
        carriers: list[dict[str, Any]] = []
        for role, member in slots:
            factor = target_factor(target, member)
            if factor is None:
                continue
            carriers.append(
                {
                    "role": role,
                    "name": _member_name(member or {}),
                    "stars": max(0, _integer(factor.get("stars")) or 0),
                }
            )
        coverage = len(carriers)
        root_carriers = sum(
            1 for carrier in carriers if carrier["role"] in {"p1", "p2"}
        )
        conditional = generation_probability(target.learned_form, coverage)
        acquisition = target.acquisition_probability
        full_probability = (
            conditional * acquisition if acquisition is not None else None
        )
        star_two_plus = distribution[2] + distribution[3]
        target_rows.append(
            {
                **target.to_dict(),
                "input_coverage": coverage,
                "input_slot_count": 6,
                "resolved_slot_count": resolved_slot_count,
                "coverage_complete": resolved_slot_count == 6,
                "input_star_sum": sum(carrier["stars"] for carrier in carriers),
                "input_star_vector": [carrier["stars"] for carrier in carriers],
                "carriers": carriers,
                "direct_parent_coverage": root_carriers,
                "generation_probability_conditional": round(conditional, 8),
                "generation_probability_full": (
                    round(full_probability, 8) if full_probability is not None else None
                ),
                "probability_two_plus_conditional": round(
                    conditional * star_two_plus, 8
                ),
                "probability_two_plus_full": (
                    round(full_probability * star_two_plus, 8)
                    if full_probability is not None
                    else None
                ),
                "expected_runs_conditional": round(1.0 / conditional, 4),
                "expected_runs_full": (
                    round(1.0 / full_probability, 4)
                    if full_probability is not None and full_probability > 0.0
                    else None
                ),
                "output_coverage_if_miss": root_carriers,
                "output_coverage_if_hit": root_carriers + 1,
                "expected_output_coverage_conditional": round(
                    root_carriers + conditional, 6
                ),
                "expected_output_coverage_full": (
                    round(root_carriers + full_probability, 6)
                    if full_probability is not None
                    else None
                ),
                "requires_own_factor": target.is_static,
                "star_distribution": {
                    str(stars): probability
                    for stars, probability in distribution.items()
                },
            }
        )
        if target.is_static and acquisition is None:
            warnings.append(
                f"{target.name} est statique, mais sa probabilité d’acquisition est inconnue."
            )

    training_aptitudes = future_parent_training_aptitudes(
        trainee,
        parent_1,
        parent_2,
    )
    aptitude_known = any(
        isinstance(payload, dict) and payload.get("initial_rank") is not None
        for dimension in training_aptitudes.values()
        if isinstance(dimension, dict)
        for payload in dimension.values()
    )
    objective_races = [
        dict(race)
        for race in trainee.get("objective_races") or []
        if isinstance(race, dict)
    ]
    race_plan = build_pair_g1_diagnostic(
        parent_1,
        parent_2,
        left_label=_member_name(parent_1),
        right_label=_member_name(parent_2),
        left_origin="local",
        right_origin="local",
        target=trainee,
        objective_races=objective_races,
        training_aptitudes=training_aptitudes if aptitude_known else None,
        win_probability_cutoff=(
            max(0.0, min(1.10, float(g1_win_probability_cutoff)))
            if aptitude_known
            else None
        ),
        max_affinity_races=max(1, min(40, int(race_budget))),
    )
    signature = _normalised_g1_signature(g1_signature)
    inherited_names = {
        str(name).casefold()
        for name in (
            list(race_plan.get("common_g1_names") or [])
            + list(race_plan.get("left_only_g1_names") or [])
            + list(race_plan.get("right_only_g1_names") or [])
        )
    }
    signature_covered = [
        name for name in signature if name.casefold() in inherited_names
    ]
    signature_missing = [
        name for name in signature if name.casefold() not in inherited_names
    ]

    return {
        "schema_version": 1,
        "trainee": _identity(trainee),
        "parent_1": _identity(parent_1),
        "parent_2": _identity(parent_2),
        "parent_1_trained_id": _integer(parent_1.get("trained_chara_id")),
        "parent_2_trained_id": _integer(parent_2.get("trained_chara_id")),
        "parent_1_fingerprint": member_fingerprint(parent_1),
        "parent_2_fingerprint": member_fingerprint(parent_2),
        "quality_band": quality_band,
        "targets": [target.to_dict() for target in selected_targets],
        "skills": target_rows,
        "lineage": {
            "resolved_slots": resolved_slot_count,
            "total_slots": 6,
            "complete": resolved_slot_count == 6,
        },
        "g1": {
            "race_budget": max(1, min(40, int(race_budget))),
            "common_names": list(race_plan.get("common_g1_names") or []),
            "left_only_names": list(race_plan.get("left_only_g1_names") or []),
            "right_only_names": list(race_plan.get("right_only_g1_names") or []),
            "scheduled_race_count": int(race_plan.get("scheduled_race_count") or 0),
            "optimal_bonus": int(race_plan.get("optimal_bonus") or 0),
            "training_aptitudes": copy.deepcopy(
                training_aptitudes if aptitude_known else None
            ),
            "win_probability_cutoff": race_plan.get("g1_win_probability_cutoff"),
            "signature": signature,
            "signature_covered": signature_covered,
            "signature_missing": signature_missing,
            "diagnostic": race_plan,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }


def targets_from_plan(plan: dict[str, Any]) -> list[LoopSkillTarget]:
    return [
        LoopSkillTarget.from_dict(item)
        for item in plan.get("targets") or []
        if isinstance(item, dict)
    ]


def _parent_reference_id(member: object) -> int | None:
    if not isinstance(member, dict):
        return None
    for key in ("local_trained_chara_id", "trained_chara_id"):
        value = _integer(member.get(key))
        if value is not None and value > 0:
            return value
    return None


def analyze_outcome(
    *,
    outcome: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    targets = targets_from_plan(plan)
    if not targets:
        raise LoopEngineError("La transition enregistrée ne contient aucune cible.")
    planned_ids = {
        _integer(plan.get("parent_1_trained_id")),
        _integer(plan.get("parent_2_trained_id")),
    }
    planned_ids.discard(None)
    planned_fingerprints = {
        str(value)
        for value in (
            plan.get("parent_1_fingerprint"),
            plan.get("parent_2_fingerprint"),
        )
        if value
    }
    lineage = outcome.get("when_used_as_parent") or {}
    if not isinstance(lineage, dict):
        lineage = {}
    parents = [lineage.get("grandparent_1"), lineage.get("grandparent_2")]
    actual_references = [_parent_reference_id(member) for member in parents]
    known_references = {value for value in actual_references if value is not None}
    actual_fingerprints = {
        value for value in (member_fingerprint(member) for member in parents) if value
    }
    if len(known_references) == 2:
        provenance = "match" if known_references == planned_ids else "mismatch"
    elif (
        len(planned_fingerprints) == 2
        and len(actual_fingerprints) == 2
    ):
        provenance = (
            "match_snapshot"
            if actual_fingerprints == planned_fingerprints
            else "mismatch"
        )
    else:
        provenance = "unknown"

    planned_trainee = plan.get("trainee") or {}
    planned_card_id = _integer(planned_trainee.get("card_id"))
    planned_chara_id = _integer(planned_trainee.get("chara_id"))
    outcome_card_id = _integer(outcome.get("card_id"))
    outcome_chara_id = _integer(outcome.get("chara_id"))
    if planned_card_id is not None and outcome_card_id is not None:
        trainee_provenance = "match" if planned_card_id == outcome_card_id else "mismatch"
    elif planned_chara_id is not None and outcome_chara_id is not None:
        trainee_provenance = "match" if planned_chara_id == outcome_chara_id else "mismatch"
    else:
        trainee_provenance = "unknown"

    rows: list[dict[str, Any]] = []
    static_hits = 0
    dynamic_hits = 0
    own_hits = 0
    for target in targets:
        own = target_factor(target, outcome)
        parent_factors = [target_factor(target, parent) for parent in parents]
        output_coverage = int(own is not None) + sum(
            factor is not None for factor in parent_factors
        )
        own_stars = max(0, _integer((own or {}).get("stars")) or 0)
        if own is not None:
            own_hits += 1
            if target.is_static:
                static_hits += 1
            else:
                dynamic_hits += 1
        rows.append(
            {
                **target.to_dict(),
                "own_factor_present": own is not None,
                "own_factor_stars": own_stars,
                "direct_parent_factor_count": sum(
                    factor is not None for factor in parent_factors
                ),
                "output_coverage": output_coverage,
                "output_slot_count": 3,
                "hard_gate_passed": own is not None if target.is_static else None,
            }
        )

    static_total = sum(target.is_static for target in targets)
    hard_targets_met = static_hits == static_total
    if provenance == "mismatch" or trainee_provenance == "mismatch":
        suggested = "review"
    elif hard_targets_met and own_hits > 0:
        suggested = "promote_core"
    elif own_hits > 0:
        suggested = "keep_side"
    else:
        suggested = "ignore"
    return {
        "outcome": _identity(outcome),
        "planned_parent_ids": sorted(int(value) for value in planned_ids),
        "actual_parent_ids": sorted(known_references),
        "parent_provenance": provenance,
        "planned_parent_fingerprints": sorted(planned_fingerprints),
        "actual_parent_fingerprints": sorted(actual_fingerprints),
        "trainee_provenance": trainee_provenance,
        "skills": rows,
        "static_target_count": static_total,
        "static_hit_count": static_hits,
        "dynamic_hit_count": dynamic_hits,
        "own_target_hit_count": own_hits,
        "hard_targets_met": hard_targets_met,
        "suggested_verdict": suggested,
    }



def _skill_name_key(value: object) -> str:
    text = str(value or "")
    for token in ("◎", "○", "◉", "(gold)", "[gold]", " gold"):
        text = text.replace(token, " ").replace(token.upper(), " ")
    return _slug(text)


def _learned_skill_form(skill: dict[str, Any]) -> str:
    explicit = str(
        skill.get("learned_form")
        or skill.get("form")
        or skill.get("grade")
        or skill.get("rarity")
        or ""
    ).strip().casefold()
    name = str(skill.get("name") or skill.get("skill_name") or "")
    if bool(skill.get("is_gold") or skill.get("is_rare")) or any(
        token in explicit for token in ("gold", "rare", "unique")
    ):
        return "gold"
    if bool(skill.get("is_double_circle")) or "◎" in name or any(
        token in explicit for token in ("double_circle", "double-circle", "double circle", "◎")
    ):
        return "double_circle"
    if bool(skill.get("is_circle")) or "○" in name or any(
        token in explicit for token in ("circle", "○")
    ):
        return "single_circle"
    if explicit in {"normal", "white", "basic"}:
        return "normal"
    return "normal" if name or _integer(skill.get("skill_id")) else "unknown"


def extract_learned_skills(member: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Return whether learned-skill data is available and a normalized list.

    Linked exports have changed shape over time. Detection deliberately accepts
    several known container names, but it never infers acquisition from White
    factors: if none of these containers exists, acquisition remains unknown.
    """

    explicit_known = member.get("learned_skills_known")
    if explicit_known is False:
        return False, []

    containers: list[object] = []
    known = bool(explicit_known)
    for key in ("learned_skills", "skills", "skill_list", "acquired_skills"):
        if key not in member:
            continue
        known = True
        containers.append(member.get(key))
    training_result = member.get("training_result")
    if isinstance(training_result, dict):
        for key in ("learned_skills", "skills"):
            if key in training_result:
                known = True
                containers.append(training_result.get(key))

    raw_items: list[object] = []
    for container in containers:
        if isinstance(container, list):
            raw_items.extend(container)
        elif isinstance(container, dict):
            values = list(container.values())
            if all(isinstance(value, (dict, int, str)) for value in values):
                raw_items.extend(values)

    result: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str, str]] = set()
    for raw in raw_items:
        if isinstance(raw, dict):
            skill = raw
            skill_id = (
                _integer(skill.get("skill_id"))
                or _integer(skill.get("id"))
                or _integer(skill.get("skillId"))
            )
            group_id = _integer(skill.get("group_id") or skill.get("groupId"))
            name = str(
                skill.get("name")
                or skill.get("skill_name")
                or skill.get("skillName")
                or ""
            ).strip()
            level = _integer(skill.get("level") or skill.get("skill_level"))
            form = _learned_skill_form(skill)
        elif isinstance(raw, int):
            skill_id = int(raw)
            group_id = None
            name = ""
            level = None
            form = "unknown"
        elif isinstance(raw, str):
            skill_id = None
            group_id = None
            name = raw.strip()
            level = None
            form = "normal" if name else "unknown"
        else:
            continue
        if not name and skill_id is None:
            continue
        key = (skill_id, _skill_name_key(name), form)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "skill_id": skill_id,
                "group_id": group_id,
                "name": name or (f"Skill #{skill_id}" if skill_id else "Skill"),
                "form": form,
                "level": level,
            }
        )
    result.sort(key=lambda row: (str(row.get("name") or "").casefold(), int(row.get("skill_id") or 0)))
    return known, result


def _target_acquisition(
    target: LoopSkillTarget,
    *,
    learned_skills_known: bool,
    learned_skills: list[dict[str, Any]],
) -> tuple[bool | None, dict[str, Any] | None]:
    if not learned_skills_known:
        return None, None
    # White factor_group_id and skill_data.group_id are the same group axis in
    # the generated skill catalog. Matching the group is what lets a normal
    # target count its circle/double-circle/gold learned variant correctly.
    if target.factor_group_id is not None:
        for skill in learned_skills:
            if _integer(skill.get("group_id")) == target.factor_group_id:
                return True, skill
    if target.skill_id is not None:
        for skill in learned_skills:
            if _integer(skill.get("skill_id")) == target.skill_id:
                return True, skill
    expected = _skill_name_key(target.name)
    if expected:
        for skill in learned_skills:
            if _skill_name_key(skill.get("name")) == expected:
                return True, skill
    return False, None


def build_run_result(
    *,
    outcome: dict[str, Any],
    plan: dict[str, Any],
    auto_detected: bool = True,
) -> LoopRunResult:
    outcome_id = _integer(outcome.get("trained_chara_id"))
    if outcome_id is None or outcome_id <= 0:
        raise LoopEngineError("Le descendant doit posséder un identifiant local.")
    analysis = analyze_outcome(outcome=outcome, plan=plan)
    learned_known, learned_skills = extract_learned_skills(outcome)
    targets = {target.key: target for target in targets_from_plan(plan)}
    for row in analysis.get("skills") or []:
        if not isinstance(row, dict):
            continue
        target = targets.get(str(row.get("key") or ""))
        if target is None:
            continue
        acquired, matched = _target_acquisition(
            target,
            learned_skills_known=learned_known,
            learned_skills=learned_skills,
        )
        row["skill_acquired"] = acquired
        row["acquired_form"] = matched.get("form") if matched else None
        row["acquired_skill_id"] = matched.get("skill_id") if matched else None
        row["acquired_skill_name"] = matched.get("name") if matched else None
        row["factor_generated"] = bool(row.get("own_factor_present"))
        row["factor_stars"] = int(row.get("own_factor_stars") or 0)
    analysis["learned_skills_known"] = learned_known
    analysis["learned_skill_count"] = len(learned_skills)
    return LoopRunResult(
        run_id=f"local:{outcome_id}",
        trained_chara_id=outcome_id,
        detected_at=utc_now(),
        snapshot=snapshot_member(outcome),
        analysis=analysis,
        learned_skills=learned_skills,
        learned_skills_known=learned_known,
        auto_detected=auto_detected,
    )


def configure_draft(
    project: LoopProject,
    *,
    trainee: dict[str, Any] | None,
    parent_1: dict[str, Any] | None,
    parent_2: dict[str, Any] | None,
    last_plan: dict[str, Any] | None = None,
) -> LoopDraftTransition | None:
    draft = LoopDraftTransition(
        trainee_card_id=_integer((trainee or {}).get("card_id")),
        trainee_chara_id=_integer((trainee or {}).get("chara_id")),
        parent_1_trained_id=_integer((parent_1 or {}).get("trained_chara_id")),
        parent_2_trained_id=_integer((parent_2 or {}).get("trained_chara_id")),
        last_plan=copy.deepcopy(last_plan),
        updated_at=utc_now(),
    )
    project.draft = None if draft.empty and draft.last_plan is None else draft
    project.touch()
    return project.draft


def detect_transition_runs(
    project: LoopProject,
    veterans: Iterable[dict[str, Any]],
) -> list[tuple[LoopTransition, LoopRunResult]]:
    """Attach newly extracted veterans to active batches using frozen provenance.

    Baseline IDs prevent historical veterans from being re-imported. For old
    schema-v1 pending transitions with no baseline, the first scan initializes
    the baseline and intentionally detects nothing.
    """

    members = [member for member in veterans if isinstance(member, dict)]
    current_ids = {
        value
        for value in (_integer(member.get("trained_chara_id")) for member in members)
        if value is not None and value > 0
    }
    assigned_ids = {
        run.trained_chara_id
        for transition in project.transitions
        for run in transition.runs
    }
    active = sorted(
        (transition for transition in project.transitions if transition.active),
        key=lambda transition: transition.created_at,
        reverse=True,
    )
    initialized = False
    for transition in active:
        if transition.baseline_trained_ids:
            continue
        transition.baseline_trained_ids = sorted(current_ids)
        initialized = True
    if initialized:
        project.touch()

    detected: list[tuple[LoopTransition, LoopRunResult]] = []
    for member in members:
        trained_id = _integer(member.get("trained_chara_id"))
        if trained_id is None or trained_id <= 0 or trained_id in assigned_ids:
            continue
        for transition in active:
            if trained_id in transition.baseline_trained_ids:
                continue
            try:
                run = build_run_result(outcome=member, plan=transition.plan, auto_detected=True)
            except LoopEngineError:
                continue
            analysis = run.analysis
            if analysis.get("trainee_provenance") != "match":
                continue
            if analysis.get("parent_provenance") not in {"match", "match_snapshot"}:
                continue
            transition.runs.append(run)
            assigned_ids.add(trained_id)
            detected.append((transition, run))
            project.touch()
            # Newest matching active batch wins. Keeping two identical batches
            # active would otherwise make provenance intrinsically ambiguous.
            break
    return detected


def transition_statistics(transition: LoopTransition) -> dict[str, Any]:
    runs = list(transition.runs)
    total = len(runs)
    target_defs = targets_from_plan(transition.plan)
    theoretical = {
        str(row.get("key") or ""): row
        for row in transition.plan.get("skills") or []
        if isinstance(row, dict)
    }
    target_rows: list[dict[str, Any]] = []
    for target in target_defs:
        rows = []
        for run in runs:
            match = next(
                (
                    row
                    for row in run.analysis.get("skills") or []
                    if isinstance(row, dict) and str(row.get("key") or "") == target.key
                ),
                None,
            )
            if match is not None:
                rows.append(match)
        acquisition_known = [row for row in rows if row.get("skill_acquired") is not None]
        acquired = [row for row in acquisition_known if bool(row.get("skill_acquired"))]
        generated = [row for row in rows if bool(row.get("factor_generated", row.get("own_factor_present")))]
        generated_given_acquired = [
            row for row in acquired if bool(row.get("factor_generated", row.get("own_factor_present")))
        ]
        ge2 = [row for row in generated if int(row.get("factor_stars", row.get("own_factor_stars")) or 0) >= 2]
        three = [row for row in generated if int(row.get("factor_stars", row.get("own_factor_stars")) or 0) >= 3]
        form_counts = {"normal": 0, "single_circle": 0, "double_circle": 0, "gold": 0, "unknown": 0}
        for row in acquired:
            form = str(row.get("acquired_form") or "unknown")
            form_counts[form if form in form_counts else "unknown"] += 1
        theory = theoretical.get(target.key) or {}
        input_coverage = max(0, min(6, int(theory.get("input_coverage") or 0)))
        expected_by_acquired_form: list[float] = []
        for row in acquired:
            form = str(row.get("acquired_form") or "unknown")
            if form == "gold":
                model_form = "gold"
            elif form == "double_circle":
                # The historical Workshop model names the ◎ tier `circle`.
                model_form = "circle"
            elif form in {"normal", "single_circle"}:
                model_form = "normal"
            else:
                model_form = target.learned_form
            expected_by_acquired_form.append(
                generation_probability(model_form, input_coverage)
            )
        conditional = (
            sum(expected_by_acquired_form) / len(expected_by_acquired_form)
            if expected_by_acquired_form
            else theory.get("generation_probability_conditional")
        )
        observed_conditional = (
            len(generated_given_acquired) / len(acquired) if acquired else None
        )
        target_rows.append(
            {
                **target.to_dict(),
                "run_count": total,
                "acquisition_known_count": len(acquisition_known),
                "acquired_count": len(acquired),
                "acquisition_rate": (
                    len(acquired) / len(acquisition_known) if acquisition_known else None
                ),
                "acquired_form_counts": form_counts,
                "factor_generated_count": len(generated),
                "factor_generation_rate_all": len(generated) / total if total else None,
                "factor_generation_rate_given_acquired": observed_conditional,
                "factor_two_plus_count": len(ge2),
                "factor_two_plus_rate_all": len(ge2) / total if total else None,
                "factor_three_star_count": len(three),
                "factor_three_star_rate_all": len(three) / total if total else None,
                "theoretical_generation_conditional": conditional,
                "generation_delta_vs_theory": (
                    observed_conditional - float(conditional)
                    if observed_conditional is not None and conditional is not None
                    else None
                ),
            }
        )

    static_keys = {target.key for target in target_defs if target.is_static}
    any_generated = 0
    any_ge2 = 0
    all_static = 0
    for run in runs:
        run_rows = [row for row in run.analysis.get("skills") or [] if isinstance(row, dict)]
        generated_keys = {
            str(row.get("key") or "")
            for row in run_rows
            if bool(row.get("factor_generated", row.get("own_factor_present")))
        }
        if generated_keys:
            any_generated += 1
        if any(
            bool(row.get("factor_generated", row.get("own_factor_present")))
            and int(row.get("factor_stars", row.get("own_factor_stars")) or 0) >= 2
            for row in run_rows
        ):
            any_ge2 += 1
        if static_keys and static_keys.issubset(generated_keys):
            all_static += 1
        elif not static_keys:
            all_static += 1

    verdict_counts = {key: 0 for key in LOOP_VERDICTS}
    reviewed = 0
    for run in runs:
        if run.verdict in verdict_counts:
            verdict_counts[run.verdict] += 1
            reviewed += 1
    return {
        "run_count": total,
        "target_stats": target_rows,
        "any_factor_generated_count": any_generated,
        "any_factor_generated_rate": any_generated / total if total else None,
        "any_factor_two_plus_count": any_ge2,
        "any_factor_two_plus_rate": any_ge2 / total if total else None,
        "all_static_generated_count": all_static,
        "all_static_generated_rate": all_static / total if total else None,
        "reviewed_run_count": reviewed,
        "verdict_counts": verdict_counts,
        "promotion_count": verdict_counts["promote_core"] + verdict_counts["replace_core"],
        "promotion_rate_reviewed": (
            (verdict_counts["promote_core"] + verdict_counts["replace_core"]) / reviewed
            if reviewed
            else None
        ),
    }

def snapshot_member(member: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "trained_chara_id",
        "card_id",
        "chara_id",
        "uma_name",
        "card_name",
        "costume_name",
        "rank",
        "rank_score",
        "scenario_id",
        "running_style",
        "stats",
        "factors",
        "skills",
        "learned_skills",
        "learned_skills_known",
        "skill_list",
        "acquired_skills",
        "g1_wins",
        "when_used_as_parent",
    )
    return {
        key: copy.deepcopy(member.get(key))
        for key in keys
        if member.get(key) is not None
    }


def carrier_id_for_member(member: dict[str, Any]) -> str:
    trained_id = _integer(member.get("trained_chara_id"))
    if trained_id is not None and trained_id > 0:
        return f"local:{trained_id}"
    canonical = json.dumps(
        snapshot_member(member), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "snapshot:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _carrier(member: dict[str, Any], branch: str) -> LoopCarrier:
    return LoopCarrier(
        carrier_id=carrier_id_for_member(member),
        trained_chara_id=_integer(member.get("trained_chara_id")),
        branch=branch,
        status="active",
        snapshot=snapshot_member(member),
    )



def record_plan(
    project: LoopProject,
    *,
    trainee: dict[str, Any],
    parent_1: dict[str, Any],
    parent_2: dict[str, Any],
    plan: dict[str, Any],
    baseline_trained_ids: Iterable[int] = (),
) -> LoopTransition:
    parent_1_id = _integer(parent_1.get("trained_chara_id"))
    parent_2_id = _integer(parent_2.get("trained_chara_id"))
    if parent_1_id is None or parent_2_id is None:
        raise LoopEngineError("Impossible d’enregistrer des parents sans identifiant local.")
    trainee_card_id = _integer(trainee.get("card_id")) or 0
    expected_parents = {parent_1_id, parent_2_id}
    for current in project.transitions:
        if not current.active:
            continue
        if current.trainee_card_id != trainee_card_id:
            continue
        if {current.parent_1_trained_id, current.parent_2_trained_id} == expected_parents:
            raise LoopEngineError(
                "Une transition identique est déjà en cours : continue ce batch ou clôture-le d’abord."
            )
    project.upsert_carrier(_carrier(parent_1, "core"))
    project.upsert_carrier(_carrier(parent_2, "core"))
    transition = new_transition(
        trainee=trainee,
        parent_1_trained_id=parent_1_id,
        parent_2_trained_id=parent_2_id,
        quality_band=str(plan.get("quality_band") or project.quality_band),
        plan=plan,
        baseline_trained_ids=[int(value) for value in baseline_trained_ids],
    )
    project.transitions.append(transition)
    project.draft = LoopDraftTransition(
        trainee_card_id=_integer(trainee.get("card_id")),
        trainee_chara_id=_integer(trainee.get("chara_id")),
        parent_1_trained_id=parent_1_id,
        parent_2_trained_id=parent_2_id,
        last_plan=copy.deepcopy(plan),
        updated_at=utc_now(),
    )
    project.touch()
    return transition


def _validate_run_verdict(
    project: LoopProject,
    *,
    outcome_id: int,
    verdict: str,
    branch: str,
    replaces_trained_chara_id: int | None,
) -> int | None:
    if verdict not in LOOP_VERDICTS:
        raise LoopEngineError(f"Verdict de looping inconnu : {verdict}")
    if branch not in BRANCH_TYPES:
        raise LoopEngineError(f"Branche de looping inconnue : {branch}")
    replacement_id = _integer(replaces_trained_chara_id)
    if verdict == "replace_core" and replacement_id is None:
        raise LoopEngineError("Choisis le porteur Core remplacé.")
    if verdict == "replace_core" and replacement_id == outcome_id:
        raise LoopEngineError("Le descendant ne peut pas se remplacer lui-même.")
    if verdict == "replace_core" and not any(
        carrier.active
        and carrier.branch == "core"
        and carrier.trained_chara_id == replacement_id
        for carrier in project.carriers
    ):
        raise LoopEngineError("Le porteur Core remplacé n’est plus actif dans ce projet.")
    return replacement_id


def record_run_verdict(
    project: LoopProject,
    *,
    transition_id: str,
    trained_chara_id: int,
    verdict: str,
    branch: str = "custom",
    replaces_trained_chara_id: int | None = None,
    note: str = "",
) -> LoopRunResult:
    transition = project.transition(transition_id)
    if transition is None:
        raise LoopEngineError("Transition de looping introuvable.")
    run = transition.run(trained_chara_id)
    if run is None:
        raise LoopEngineError("Résultat de run introuvable dans ce batch.")
    if run.reviewed_at:
        raise LoopEngineError("Ce résultat de batch possède déjà un verdict.")
    replacement_id = _validate_run_verdict(
        project,
        outcome_id=run.trained_chara_id,
        verdict=verdict,
        branch=branch,
        replaces_trained_chara_id=replaces_trained_chara_id,
    )
    run.verdict = verdict
    run.branch = "core" if verdict in {"promote_core", "replace_core"} else branch
    run.replaces_trained_chara_id = replacement_id
    run.note = str(note or "")
    run.reviewed_at = utc_now()

    if verdict != "ignore":
        project.upsert_carrier(
            _carrier(
                run.snapshot,
                "core" if verdict in {"promote_core", "replace_core"} else branch,
            )
        )
    if verdict == "replace_core" and replacement_id is not None:
        for carrier in project.carriers:
            if carrier.trained_chara_id == replacement_id:
                carrier.status = "archived"
                carrier.note = (
                    f"Remplacé par le vétéran #{run.trained_chara_id} via le batch "
                    f"{transition.transition_id}."
                )
    project.touch()
    return run


def close_transition(project: LoopProject, *, transition_id: str) -> LoopTransition:
    transition = project.transition(transition_id)
    if transition is None:
        raise LoopEngineError("Transition de looping introuvable.")
    if transition.status == "completed":
        return transition
    transition.status = "completed"
    transition.completed_at = utc_now()
    project.touch()
    return transition


def add_manual_run(
    project: LoopProject,
    *,
    transition_id: str,
    outcome: dict[str, Any],
) -> LoopRunResult:
    transition = project.transition(transition_id)
    if transition is None:
        raise LoopEngineError("Transition de looping introuvable.")
    outcome_id = _integer(outcome.get("trained_chara_id"))
    if outcome_id is None or outcome_id <= 0:
        raise LoopEngineError("Le descendant doit posséder un identifiant local.")
    existing = transition.run(outcome_id)
    if existing is not None:
        return existing
    run = build_run_result(outcome=outcome, plan=transition.plan, auto_detected=False)
    transition.runs.append(run)
    project.touch()
    return run


def complete_transition(
    project: LoopProject,
    *,
    transition_id: str,
    outcome: dict[str, Any],
    analysis: dict[str, Any],
    verdict: str,
    branch: str = "custom",
    replaces_trained_chara_id: int | None = None,
    note: str = "",
) -> LoopTransition:
    """Compatibility wrapper for the old one-outcome lifecycle.

    New Workshop UI keeps a batch active after reviewing one run. Older callers
    may still use complete_transition(); it records the run, applies its verdict,
    mirrors the legacy fields, then explicitly closes the batch.
    """

    transition = project.transition(transition_id)
    if transition is None:
        raise LoopEngineError("Transition de looping introuvable.")
    if transition.status != "pending":
        raise LoopEngineError("Cette transition de looping est déjà terminée.")
    outcome_id = _integer(outcome.get("trained_chara_id"))
    if outcome_id is None:
        raise LoopEngineError("Le descendant doit posséder un identifiant local.")
    run = transition.run(outcome_id)
    if run is None:
        run = build_run_result(outcome=outcome, plan=transition.plan, auto_detected=False)
        if isinstance(analysis, dict) and analysis:
            # Keep caller-provided provenance/target analysis, but preserve the
            # acquisition enrichment computed from the extracted veteran.
            enriched = run.analysis
            merged = copy.deepcopy(analysis)
            enriched_by_key = {
                str(row.get("key") or ""): row
                for row in enriched.get("skills") or []
                if isinstance(row, dict)
            }
            for row in merged.get("skills") or []:
                if not isinstance(row, dict):
                    continue
                source = enriched_by_key.get(str(row.get("key") or "")) or {}
                for key in (
                    "skill_acquired",
                    "acquired_form",
                    "acquired_skill_id",
                    "acquired_skill_name",
                    "factor_generated",
                    "factor_stars",
                ):
                    if key in source:
                        row[key] = source[key]
            merged["learned_skills_known"] = enriched.get("learned_skills_known")
            merged["learned_skill_count"] = enriched.get("learned_skill_count")
            run.analysis = merged
        transition.runs.append(run)
    record_run_verdict(
        project,
        transition_id=transition_id,
        trained_chara_id=outcome_id,
        verdict=verdict,
        branch=branch,
        replaces_trained_chara_id=replaces_trained_chara_id,
        note=note,
    )
    # Mirror legacy fields for downstream code that has not migrated yet.
    transition.outcome_trained_chara_id = outcome_id
    transition.verdict = verdict
    transition.branch = "core" if verdict in {"promote_core", "replace_core"} else branch
    transition.replaces_trained_chara_id = _integer(replaces_trained_chara_id)
    transition.outcome_analysis = copy.deepcopy(run.analysis)
    transition.note = str(note or "")
    close_transition(project, transition_id=transition_id)
    return transition

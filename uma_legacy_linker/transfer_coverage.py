from __future__ import annotations

from typing import Any, Iterable

from uma_legacy_linker.transfer_portfolio import minimum_portfolio


def _score(record: dict[str, Any]) -> float:
    try:
        return float(record.get("rank_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _id_key(record: dict[str, Any]) -> str:
    return str(record.get("trained_chara_id") or "")


def _reference(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "trained_chara_id": record.get("trained_chara_id"),
        "rank_score": record.get("rank_score"),
        "card_name": record.get("card_name"),
        "uma_name": record.get("uma_name"),
        "rank": record.get("rank"),
    }


def _profile_score(
    record: dict[str, Any],
    role: str,
    context_key: str,
    ace_index: int | None = None,
) -> float | None:
    profiles = record.get(f"_{role}_profiles") or []
    for profile in profiles:
        if str(profile.get("context_key") or "") == context_key:
            scores = profile.get("ace_scores") or []
            try:
                value = scores[ace_index] if ace_index is not None else profile.get("score")
                return float(value) if value is not None else None
            except (IndexError, TypeError, ValueError):
                return None
    return None


def _minimum_cover(
    requirement_keys: Iterable[str],
    requirements: dict[str, dict[str, Any]],
    candidates: set[int],
    records: list[dict[str, Any]],
) -> list[int]:
    """Return the solver's deterministic minimum retained set for these keys."""
    keys = tuple(sorted(set(requirement_keys)))
    if not keys:
        return []
    carrier_sets = [
        set(requirements[key].get("covered_by") or ()) & candidates
        for key in keys
    ]
    if any(not carriers for carriers in carrier_sets):
        return []
    selected = minimum_portfolio(
        candidates,
        carrier_sets,
        priorities={
            index: (_score(records[index]), _id_key(records[index]))
            for index in candidates
        },
    ).selected
    return sorted(selected, key=lambda index: (-_score(records[index]), _id_key(records[index])))


def _candidate_gaps(
    candidate_index: int,
    retained_indices: Iterable[int],
    requirements: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    retained = tuple(index for index in retained_indices if index != candidate_index)
    gaps: list[dict[str, Any]] = []
    for key, requirement in requirements.items():
        if (
            requirement.get("kind") != "performance"
            or candidate_index not in set(requirement.get("covered_by") or ())
        ):
            continue
        role = str(requirement.get("role") or "")
        context_key = str(requirement.get("context_key") or "")
        ace_index = requirement.get("ace_index")
        candidate_score = _profile_score(records[candidate_index], role, context_key, ace_index)
        if candidate_score is None:
            continue
        alternatives = [
            score
            for index in retained
            if (score := _profile_score(records[index], role, context_key, ace_index)) is not None
        ]
        if not alternatives:
            continue
        best_retained = max(alternatives)
        gaps.append(
            {
                "gap": round(candidate_score - best_retained, 6),
                "role": role,
                "context_key": context_key,
                "profile": str(requirement.get("label") or context_key),
                "candidate_score": round(candidate_score, 6),
                "replacement_score": round(best_retained, 6),
            }
        )
    return gaps


def _strict_gap(record: dict[str, Any]) -> dict[str, Any] | None:
    replacement = record.get("dominated_by") or {}
    rows = replacement.get("context_deltas") or []
    valid = [
        row for row in rows
        if row.get("candidate_score") is not None
        and row.get("replacement_score") is not None
    ]
    if not valid:
        return None
    worst = min(
        valid,
        key=lambda row: float(row.get("candidate_score") or 0.0)
        - float(row.get("replacement_score") or 0.0),
    )
    return {
        "gap": round(
            float(worst.get("candidate_score") or 0.0)
            - float(worst.get("replacement_score") or 0.0),
            6,
        ),
        "role": str(worst.get("role") or ""),
        "context_key": str(worst.get("context_key") or ""),
        "profile": str(worst.get("profile") or worst.get("context_key") or ""),
        "candidate_score": worst.get("candidate_score"),
        "replacement_score": worst.get("replacement_score"),
        "gap_count": len(valid),
    }


def _kept_reason(
    candidate_index: int,
    group_indices: list[int],
    selected: set[int],
    requirements: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    record = records[candidate_index]
    manual = list(record.get("manual_protection_reasons") or [])
    if manual:
        return {
            "code": "protected",
            "refs": [],
            "subject": manual[0],
            "model_reasons": manual,
            "model_status": record.get("analysis_status"),
            "model_reason": record.get("analysis_reason_code"),
            "more": max(0, len(manual) - 1),
        }

    required = list(record.get("portfolio_required_for") or [])
    protected_assets = [
        item for item in required
        if item.get("kind") in {"protected_skill", "protected_package"}
    ]
    three_star_assets = [
        item for item in required
        if item.get("kind") in {"pink_3star", "blue_3star"}
    ]
    assets = protected_assets or three_star_assets
    if assets:
        chosen = sorted(
            assets,
            key=lambda item: (
                str(item.get("label") or item.get("key") or "").casefold(),
                str(item.get("key") or ""),
            ),
        )[0]
        return {
            "code": "carries_asset",
            "refs": [],
            "subject": str(chosen.get("label") or chosen.get("key") or ""),
            "more": max(0, len(assets) - 1),
        }

    loop_items = sorted(
        (item for item in required if item.get("kind") in {"loop_skill", "loop_preset", "loop_floor"}),
        key=lambda item: (
            0 if item.get("kind") == "loop_preset" else 1,
            -int(item.get("package_score") or item.get("loop_presence_count") or 0),
            -int(bool(item.get("direct"))),
            str(item.get("label") or "").casefold(),
        ),
    )
    if loop_items:
        return {
            "code": "loop_carrier",
            "refs": [],
            "subject": str(loop_items[0].get("label") or ""),
            "loop_skills": [
                {
                    "label": str(item.get("label") or ""),
                    "presence_count": int(item.get("loop_presence_count") or 0),
                    "direct": bool(item.get("direct")),
                    "already_retained_for_performance": bool(
                        item.get("was_previously_selected")
                    ),
                }
                for item in loop_items if item.get("kind") == "loop_skill"
            ],
            "loop_packages": [
                {
                    "label": str(item.get("label") or ""),
                    "preset": str(item.get("preset_key") or ""),
                    "score": int(item.get("package_score") or 0),
                    "maximum": int(item.get("package_max") or 0),
                    "already_retained_for_performance": bool(item.get("was_previously_selected")),
                }
                for item in loop_items if item.get("kind") == "loop_preset"
            ],
            "loop_floors": [
                {
                    "label": str(item.get("label") or ""),
                    "skill_name": str(item.get("skill_name") or item.get("skill_key") or ""),
                    "presence_count": int(item.get("loop_presence_count") or 0),
                    "best_presence_count": int(item.get("best_presence_count") or 0),
                    "sole_source": bool(item.get("sole_source")),
                    "already_retained_for_performance": bool(item.get("was_previously_selected")),
                }
                for item in loop_items if item.get("kind") == "loop_floor"
            ],
            "loop_count": len(loop_items),
            "more": max(0, len(loop_items) - 1),
        }

    unique_performance = [
        (key, item)
        for key, item in requirements.items()
        if item.get("kind") == "performance"
        and candidate_index in set(item.get("covered_by") or ())
        and (set(item.get("covered_by") or ()) & selected) == {candidate_index}
    ]
    if unique_performance:
        alternatives = selected - {candidate_index}
        ranked: list[tuple[float, str, dict[str, Any]]] = []
        unique_roles: set[tuple[str, str]] = set()
        for key, item in unique_performance:
            role = str(item.get("role") or "")
            context_key = str(item.get("context_key") or "")
            ace_index = item.get("ace_index")
            best_score = float(item.get("best_score") or 0.0)
            alternative_scores = [
                score
                for index in alternatives
                if (score := _profile_score(records[index], role, context_key, ace_index)) is not None
            ]
            loss = max(0.0, best_score - max(alternative_scores)) if alternative_scores else best_score
            unique_roles.add((role, context_key))
            ranked.append((loss, str(key), item))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        loss, _key, chosen = ranked[0]
        subject = str(chosen.get("label") or chosen.get("context_key") or "")
        role_prefix = f"{chosen.get('role')}: "
        if subject.casefold().startswith(role_prefix.casefold()):
            subject = subject[len(role_prefix):]
        return {
            "code": "holds_role",
            "refs": [],
            "subject": subject,
            "more": max(0, len(unique_roles) - 1),
            "worst_gap": round(-loss, 6),
            "gap_count": len(unique_roles),
            "gap_role": {
                "role": str(chosen.get("role") or ""),
                "context_key": str(chosen.get("context_key") or ""),
                "profile": str(chosen.get("label") or chosen.get("context_key") or ""),
            },
        }

    if len(group_indices) == 1:
        return {
            "code": "last_copy",
            "refs": [],
            "subject": "",
            "more": 0,
        }

    return {
        "code": "insufficient",
        "refs": [],
        "subject": str(record.get("reason_code") or ""),
        "more": 0,
    }


def _closest_top_gap(
    candidate_index: int,
    requirements: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any] | None:
    gaps: list[dict[str, Any]] = []
    for requirement in requirements.values():
        if requirement.get("kind") != "performance":
            continue
        role = str(requirement.get("role") or "")
        context_key = str(requirement.get("context_key") or "")
        ace_index = requirement.get("ace_index")
        candidate_score = _profile_score(records[candidate_index], role, context_key, ace_index)
        if candidate_score is None:
            continue
        best_score = float(requirement.get("best_score") or 0.0)
        gaps.append({
            "gap": round(max(0.0, best_score - candidate_score), 6),
            "role": role,
            "context_key": context_key,
            "profile": str(requirement.get("label") or context_key),
        })
    if not gaps:
        return None
    return min(gaps, key=lambda item: (item["gap"], item["profile"]))


def _role_summaries(
    candidate_index: int,
    group_indices: list[int],
    selected: set[int],
    requirements: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    regret_tolerance: float,
) -> list[dict[str, Any]]:
    """Collapse per-Ace solver requirements into readable role/profile rows."""
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for requirement in requirements.values():
        if requirement.get("kind") != "performance":
            continue
        role = str(requirement.get("role") or "")
        context_key = str(requirement.get("context_key") or "")
        score = _profile_score(
            records[candidate_index], role, context_key, requirement.get("ace_index")
        )
        if score is None:
            continue
        profile_key = (
            role,
            str(requirement.get("surface") or ""),
            str(requirement.get("distance") or ""),
            str(requirement.get("style") or ""),
        )
        best = float(requirement.get("best_score") or 0.0)
        retained = []
        challengers = []
        for index in group_indices:
            other = _profile_score(
                records[index], role, context_key, requirement.get("ace_index")
            )
            if other is None:
                continue
            row = (other, index)
            if index in selected:
                retained.append(row)
            elif index != candidate_index:
                challengers.append(row)
        held = (
            candidate_index in selected
            and best - score <= regret_tolerance + 1e-9
            and not any(
                index != candidate_index and value >= best - regret_tolerance - 1e-9
                for value, index in retained
            )
        )
        holder_score, holder_index = max(retained, default=(None, None))
        other_retained = [row for row in retained if row[1] != candidate_index]
        other_holder_score, other_holder_index = max(other_retained, default=(None, None))
        challenger_score, challenger_index = max(challengers, default=(None, None))
        context_item = {
            "context_key": context_key,
            "ace_index": requirement.get("ace_index"),
            "ace_card_id": requirement.get("ace_card_id"),
            "best": round(best, 6),
            "score": round(score, 6),
            "gap": round(max(0.0, best - score), 6),
            "course_key": requirement.get("course_key"),
            "scope": requirement.get("scope"),
            "holder": _reference(records[holder_index]) if holder_index is not None else None,
            "holder_score": round(holder_score, 6) if holder_score is not None else None,
            "other_holder": _reference(records[other_holder_index]) if other_holder_index is not None else None,
            "other_holder_score": round(other_holder_score, 6) if other_holder_score is not None else None,
            "challenger": _reference(records[challenger_index]) if challenger_index is not None else None,
            "challenger_score": round(challenger_score, 6) if challenger_score is not None else None,
            "held": held,
            "label": str(requirement.get("label") or context_key),
        }
        grouped.setdefault(profile_key, []).append(context_item)

    result = []
    for (role, surface, distance, style), contexts in grouped.items():
        held_contexts = [item for item in contexts if item["held"]]
        # For kept copies, the tightest held niche is the one closest to leaving
        # the solver's top band. For transfer candidates, show the nearest role.
        pool = held_contexts or contexts
        worst = max(pool, key=lambda item: (item["gap"], item["context_key"], item["ace_index"] or -1))
        result.append({
            "role": role,
            "surface": surface,
            "distance": distance,
            "style": style,
            "profile": " · ".join(value for value in (surface, distance, style) if value),
            "contexts": sorted({item["context_key"] for item in contexts}),
            "courses": sorted({str(item["course_key"]) for item in contexts if item.get("course_key")}),
            "scopes": sorted({str(item["scope"]) for item in contexts if item.get("scope")}),
            **worst,
            "regret_tolerance": float(regret_tolerance),
            "scale_max": max(6.0, 1.2 * max(item["gap"] for item in contexts)),
            "context_count": len({item["context_key"] for item in contexts}),
        })
    result.sort(key=lambda item: (
        0 if item["held"] else 1,
        max(0.0, regret_tolerance - item["gap"]) if item["held"] else item["gap"],
        item["profile"], item["role"],
    ))
    return result


def _with_roles(reason, candidate_index, group_indices, selected, requirements, records, regret_tolerance):
    roles = _role_summaries(
        candidate_index, group_indices, selected, requirements, records, regret_tolerance
    )
    if (records[candidate_index].get("status") in {"keep", "protected"}
            or reason.get("code") in {"holds_role", "carries_asset", "last_copy"}):
        roles = [item for item in roles if item.get("held")]
    elif reason.get("code") in {"outclassed", "covered_by"}:
        outside = [item for item in roles if item["gap"] > regret_tolerance + 1e-9]
        # A portfolio-covered copy may have no single role inside the top
        # band. Keep its closest roles visible so the report can explain the
        # collective replacement and provide an honest point of comparison.
        roles = sorted(outside or roles, key=lambda item: (item["gap"], item["profile"]))[:3]
    else:
        # A positive transfer row only lists roles where both the copy and its
        # retained holder fit inside the same solver tolerance band.
        roles = [item for item in roles
                 if item["gap"] <= regret_tolerance + 1e-9
                 and item.get("holder_score") is not None
                 and float(item["best"]) - float(item["holder_score"]) <= regret_tolerance + 1e-9]
    reason["roles"] = roles
    return reason


def build_transfer_reason(
    candidate_index: int,
    group_indices: list[int],
    selected: set[int],
    requirements: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    regret_tolerance: float = 2.5,
) -> dict[str, Any]:
    """Build the line-level verdict rationale from solver evidence."""
    record = records[candidate_index]
    status = str(record.get("status") or "")
    if status in {"keep", "protected"}:
        reason = _kept_reason(
            candidate_index,
            group_indices,
            selected,
            requirements,
            records,
        )
        loop_requirements = [
            item for item in record.get("portfolio_required_for") or []
            if item.get("kind") in {"loop_skill", "loop_preset", "loop_floor"}
        ]
        loop_skills = [
            {
                "label": str(item.get("label") or ""),
                "presence_count": int(item.get("loop_presence_count") or 0),
                "direct": bool(item.get("direct")),
                "already_retained_for_performance": bool(item.get("was_previously_selected")),
            }
            for item in loop_requirements if item.get("kind") == "loop_skill"
        ]
        loop_packages = [
            {
                "label": str(item.get("label") or ""),
                "preset": str(item.get("preset_key") or ""),
                "score": int(item.get("package_score") or 0),
                "maximum": int(item.get("package_max") or 0),
                "already_retained_for_performance": bool(item.get("was_previously_selected")),
            }
            for item in loop_requirements if item.get("kind") == "loop_preset"
        ]
        loop_floors = [
            {
                "label": str(item.get("label") or ""),
                "presence_count": int(item.get("loop_presence_count") or 0),
                "best_presence_count": int(item.get("best_presence_count") or 0),
                "sole_source": bool(item.get("sole_source")),
                "already_retained_for_performance": bool(item.get("was_previously_selected")),
            }
            for item in loop_requirements if item.get("kind") == "loop_floor"
        ]
        if loop_skills:
            reason["loop_skills"] = loop_skills
        if loop_packages:
            reason["loop_packages"] = loop_packages
        if loop_floors:
            reason["loop_floors"] = loop_floors
        return _with_roles(reason, candidate_index, group_indices, selected, requirements, records, regret_tolerance)
    if status == "review":
        return _with_roles({
            "code": "insufficient",
            "refs": [],
            "subject": str(record.get("reason_code") or ""),
            "more": 0,
        }, candidate_index, group_indices, selected, requirements, records, regret_tolerance)
    if status == "safe_transfer":
        replacement = record.get("dominated_by") or {}
        refs = [_reference(replacement)] if replacement else []
        gap = _strict_gap(record)
        result: dict[str, Any] = {
            "code": "replaced_by" if refs else "insufficient",
            "refs": refs,
            "subject": "",
            "more": 0,
        }
        if gap is not None:
            result["worst_gap"] = gap["gap"]
            result["gap_count"] = gap.get("gap_count", 0)
            result["gap_role"] = {
                key: gap[key] for key in ("role", "context_key", "profile")
            }
        return _with_roles(result, candidate_index, group_indices, selected, requirements, records, regret_tolerance)

    candidate_requirements = {
        key: requirement
        for key, requirement in requirements.items()
        if key != "identity"
        and candidate_index in set(requirement.get("covered_by") or ())
    }
    ref_indices = _minimum_cover(
        candidate_requirements,
        requirements,
        selected - {candidate_index},
        records,
    )
    if not candidate_requirements or not ref_indices:
        result = {
            "code": "outclassed",
            "refs": [],
            "subject": "",
            "more": 0,
        }
        closest = _closest_top_gap(candidate_index, requirements, records)
        if closest is not None:
            result["closest_top_gap"] = closest["gap"]
            result["gap_role"] = {
                key: closest[key] for key in ("role", "context_key", "profile")
            }
        return _with_roles(result, candidate_index, group_indices, selected, requirements, records, regret_tolerance)

    gaps = _candidate_gaps(
        candidate_index,
        ref_indices,
        candidate_requirements,
        records,
    )
    worst = min(gaps, key=lambda item: (item["gap"], item["profile"])) if gaps else None
    result = {
        "code": "covered_by",
        "refs": [_reference(records[index]) for index in ref_indices],
        "subject": "",
        "more": 0,
    }
    if worst is not None:
        result["worst_gap"] = worst["gap"]
        result["gap_count"] = len({(item["role"], item["context_key"]) for item in gaps})
        result["gap_role"] = {
            key: worst[key] for key in ("role", "context_key", "profile")
        }
    return _with_roles(result, candidate_index, group_indices, selected, requirements, records, regret_tolerance)

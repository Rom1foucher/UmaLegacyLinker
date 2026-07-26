from __future__ import annotations

from typing import Any, Iterable

from skill_catalog import slugify


REVIEW = "review"
LIKELY_KEEP = "likely_keep"


def _factor_list(member: dict[str, Any] | None, factor_type: str) -> list[dict[str, Any]]:
    if not member:
        return []
    factors = member.get("factors") or {}
    return list((factors.get("by_type") or {}).get(factor_type) or [])


def _lineage_members(veteran: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    lineage = veteran.get("when_used_as_parent") or {}
    members = [(veteran, "parent", "parent")]
    for key in ("grandparent_1", "grandparent_2"):
        member = lineage.get(key)
        if member:
            members.append((member, "grandparent", key))
    return members


def _race_factors(member: dict[str, Any]) -> list[dict[str, Any]]:
    """Accept both current and older linked-export names without double counting."""
    factors = [*_factor_list(member, "white_race"), *_factor_list(member, "race")]
    seen: set[tuple[Any, ...]] = set()
    result: list[dict[str, Any]] = []
    for factor in factors:
        signature = (
            factor.get("factor_id"),
            factor.get("factor_group_id"),
            str(factor.get("name") or ""),
            factor.get("stars"),
        )
        if signature in seen:
            continue
        seen.add(signature)
        result.append(factor)
    return result


def skill_catalog_metadata(skill_catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for group in skill_catalog.get("white_skill_spark_groups") or []:
        key = str(group.get("catalog_key") or "")
        if not key:
            continue
        raw_count = group.get("direct_support_hint_card_count")
        support_count = (
            int(raw_count)
            if isinstance(raw_count, int) and not isinstance(raw_count, bool) and raw_count >= 0
            else None
        )
        metadata[key] = {
            "name": str(group.get("spark_name") or key),
            "direct_support_hint_card_count": support_count,
        }
    return metadata


def effective_skill_keys(
    veterans: Iterable[dict[str, Any]],
    race_skill_map: dict[str, list[str]],
    protection_config: dict[str, Any],
) -> set[str]:
    """Return every effective inherited skill that may need contextual utility."""
    keys: set[str] = set()
    for veteran in veterans:
        for member, _position, _role in _lineage_members(veteran):
            for factor in _factor_list(member, "white_skill"):
                key = slugify(str(factor.get("name") or ""))
                if key:
                    keys.add(key)
            for factor in _race_factors(member):
                keys.update(
                    key
                    for key in race_skill_map.get(str(factor.get("name") or ""), [])
                    if key
                )
    for package in protection_config.get("important_packages") or []:
        if not isinstance(package, dict):
            continue
        keys.update(str(key) for key in package.get("skills") or [] if str(key))
    return keys


def _source_probability(sources: Iterable[dict[str, Any]], event_count: int) -> float:
    failure_probability = 1.0
    for source in sources:
        rate = max(0.0, min(1.0, float(source.get("base_proc_rate") or 0.0)))
        failure_probability *= (1.0 - rate) ** event_count
    return max(0.0, min(1.0, 1.0 - failure_probability))


def _compact_skill(skill: dict[str, Any] | None) -> dict[str, Any]:
    if not skill:
        return {
            "present": False,
            "carrier_count": 0,
            "total_stars": 0,
            "neutral_probability": 0.0,
            "direct": False,
            "direct_total_stars": 0,
            "direct_white_max_stars": 0,
            "direct_neutral_probability": 0.0,
            "white_generation_carrier_count": 0,
        }
    return {
        "present": True,
        "name": skill.get("name"),
        "catalog_key": skill.get("catalog_key"),
        "carrier_count": int(skill.get("carrier_count") or 0),
        "total_stars": int(skill.get("total_stars") or 0),
        "neutral_probability": round(float(skill.get("neutral_probability") or 0.0), 8),
        "direct": bool(skill.get("direct")),
        "direct_total_stars": int(skill.get("direct_total_stars") or 0),
        "direct_white_max_stars": int(skill.get("direct_white_max_stars") or 0),
        "direct_neutral_probability": round(
            float(skill.get("direct_neutral_probability") or 0.0), 8
        ),
        "white_generation_carrier_count": int(
            skill.get("white_generation_carrier_count") or 0
        ),
        "max_context_weight": round(float(skill.get("max_context_weight") or 0.0), 6),
        "max_context": skill.get("max_context"),
        "direct_support_hint_card_count": skill.get(
            "direct_support_hint_card_count"
        ),
        "source_types": list(skill.get("source_types") or []),
    }


def build_spark_heritage(
    veteran: dict[str, Any],
    race_skill_map: dict[str, list[str]],
    skill_catalog: dict[str, Any],
    active_skill_utility: dict[str, dict[str, Any]],
    scoring_config: dict[str, Any],
) -> dict[str, Any]:
    """Normalize direct white and skill-granting Race Sparks by effective skill."""
    protection = ((scoring_config.get("transfer_helper") or {}).get("spark_protection") or {})
    white = scoring_config.get("white_inheritance") or {}
    white_rates = white.get("base_proc_rates") or {"1": 0.03, "2": 0.06, "3": 0.09}
    race_rates = white.get("race_base_proc_rates") or {"1": 0.01, "2": 0.02, "3": 0.03}
    event_count = max(1, int(white.get("inspiration_event_count", 2) or 2))
    catalog_metadata = skill_catalog_metadata(skill_catalog)
    support_overrides = protection.get("support_hint_count_overrides") or {}

    grouped: dict[str, dict[str, Any]] = {}

    def register(
        *,
        skill_key: str,
        skill_name: str,
        member_role: str,
        position: str,
        source_type: str,
        source_factor_name: str,
        stars: int,
        base_rate: float,
    ) -> None:
        if not skill_key:
            return
        bucket = grouped.setdefault(
            skill_key,
            {
                "catalog_key": skill_key,
                "name": skill_name or catalog_metadata.get(skill_key, {}).get("name") or skill_key,
                "sources": [],
            },
        )
        if source_type == "white_skill" and skill_name:
            bucket["name"] = skill_name
        bucket["sources"].append(
            {
                "member_role": member_role,
                "position": position,
                "source_type": source_type,
                "source_factor_name": source_factor_name,
                "stars": stars,
                "base_proc_rate": round(base_rate, 8),
            }
        )

    for member, position, role in _lineage_members(veteran):
        for factor in _factor_list(member, "white_skill"):
            stars = max(0, int(factor.get("stars") or 0))
            name = str(factor.get("name") or "")
            register(
                skill_key=slugify(name),
                skill_name=name,
                member_role=role,
                position=position,
                source_type="white_skill",
                source_factor_name=name,
                stars=stars,
                base_rate=max(0.0, float(white_rates.get(str(stars), 0.0))),
            )
        for factor in _race_factors(member):
            stars = max(0, int(factor.get("stars") or 0))
            race_name = str(factor.get("name") or "")
            for skill_key in race_skill_map.get(race_name, []):
                register(
                    skill_key=skill_key,
                    skill_name=str(
                        catalog_metadata.get(skill_key, {}).get("name") or skill_key
                    ),
                    member_role=role,
                    position=position,
                    source_type="white_race",
                    source_factor_name=race_name,
                    stars=stars,
                    base_rate=max(0.0, float(race_rates.get(str(stars), 0.0))),
                )

    minimum_weight = float(protection.get("minimum_context_weight", 0.55))
    hard_minimum_weight = float(
        protection.get("hard_to_obtain_minimum_context_weight", 0.60)
    )
    hard_support_ceiling = int(
        protection.get("hard_to_obtain_max_support_hint_count", 0)
    )
    repeated_min_carriers = int(
        protection.get("repeated_review_min_carriers", 2)
    )
    repeated_min_stars = int(
        protection.get("repeated_review_min_total_stars", 4)
    )
    repeated_min_probability = float(
        protection.get("repeated_review_min_probability", 0.15)
    )
    repeated_strong_carriers = int(
        protection.get("repeated_strong_min_carriers", 3)
    )
    repeated_strong_probability = float(
        protection.get("repeated_strong_min_probability", 0.28)
    )
    direct_minimum_weight = float(
        protection.get("direct_future_gp_minimum_context_weight", 0.80)
    )
    direct_min_stars = int(protection.get("direct_future_gp_min_stars", 3))

    for key, bucket in grouped.items():
        sources = list(bucket["sources"])
        direct_sources = [
            source for source in sources if str(source.get("position")) == "parent"
        ]
        white_sources = [
            source for source in sources if source.get("source_type") == "white_skill"
        ]
        utility = active_skill_utility.get(key) or {}
        max_weight = max(0.0, float(utility.get("weight") or 0.0))
        catalog_count = catalog_metadata.get(key, {}).get(
            "direct_support_hint_card_count"
        )
        override_count = support_overrides.get(key)
        if (
            isinstance(override_count, int)
            and not isinstance(override_count, bool)
            and override_count >= 0
        ):
            support_count: int | None = override_count
            support_source = "configuration_override"
        else:
            support_count = catalog_count
            support_source = "current_master" if catalog_count is not None else "unknown"

        carriers = {str(source["member_role"]) for source in sources}
        total_stars = sum(int(source.get("stars") or 0) for source in sources)
        probability = _source_probability(sources, event_count)
        direct_probability = _source_probability(direct_sources, event_count)
        signals: list[dict[str, Any]] = []

        repeated = (
            max_weight >= minimum_weight
            and len(carriers) >= repeated_min_carriers
            and total_stars >= repeated_min_stars
            and probability >= repeated_min_probability
        )
        if repeated:
            strong = (
                len(carriers) >= repeated_strong_carriers
                or probability >= repeated_strong_probability
            )
            signals.append(
                {
                    "reason_code": "protected_repeated_white_spark",
                    "strength": LIKELY_KEEP if strong else REVIEW,
                }
            )

        direct_total_stars = sum(
            int(source.get("stars") or 0) for source in direct_sources
        )
        direct_white_max_stars = max(
            (
                int(source.get("stars") or 0)
                for source in direct_sources
                if source.get("source_type") == "white_skill"
            ),
            default=0,
        )
        if (
            max_weight >= direct_minimum_weight
            and direct_white_max_stars >= direct_min_stars
        ):
            signals.append(
                {
                    "reason_code": "protected_direct_future_gp_spark",
                    "strength": LIKELY_KEEP,
                }
            )

        if (
            max_weight >= hard_minimum_weight
            and support_count is not None
            and support_count <= hard_support_ceiling
        ):
            hard_is_strong = bool(
                direct_white_max_stars >= direct_min_stars or repeated
            )
            signals.append(
                {
                    "reason_code": "protected_hard_to_obtain_spark",
                    "strength": LIKELY_KEEP if hard_is_strong else REVIEW,
                }
            )

        bucket.update(
            {
                "carrier_count": len(carriers),
                "total_stars": total_stars,
                "neutral_probability": round(probability, 8),
                "direct": bool(direct_sources),
                "direct_total_stars": direct_total_stars,
                "direct_white_max_stars": direct_white_max_stars,
                "direct_neutral_probability": round(direct_probability, 8),
                "white_generation_carrier_count": len(
                    {str(source["member_role"]) for source in white_sources}
                ),
                "max_context_weight": round(max_weight, 6),
                "max_context": utility.get("context"),
                "direct_support_hint_card_count": support_count,
                "support_hint_count_source": support_source,
                "source_types": sorted(
                    {str(source.get("source_type")) for source in sources}
                ),
                "protection_signals": signals,
            }
        )

    packages: list[dict[str, Any]] = []
    for raw_package in protection.get("important_packages") or []:
        if not isinstance(raw_package, dict):
            continue
        package_skills = [str(key) for key in raw_package.get("skills") or []]
        relevant_skills = [
            key
            for key in package_skills
            if float((grouped.get(key) or {}).get("max_context_weight") or 0.0)
            >= minimum_weight
        ]
        present_skills = [key for key in relevant_skills if key in grouped]
        total_stars = sum(
            int((grouped.get(key) or {}).get("total_stars") or 0)
            for key in present_skills
        )
        review_min = int(raw_package.get("review_min_distinct", 1))
        strong_min = int(raw_package.get("strong_min_distinct", len(package_skills)))
        review_stars = int(raw_package.get("review_min_total_stars", 0))
        strong_stars = int(raw_package.get("strong_min_total_stars", review_stars))
        if len(present_skills) >= strong_min and total_stars >= strong_stars:
            level: str | None = LIKELY_KEEP
        elif len(present_skills) >= review_min and total_stars >= review_stars:
            level = REVIEW
        else:
            level = None
        packages.append(
            {
                "key": str(raw_package.get("key") or ""),
                "label": str(raw_package.get("label") or raw_package.get("key") or ""),
                "skills": package_skills,
                "relevant_skills": relevant_skills,
                "present_skills": present_skills,
                "distinct_count": len(present_skills),
                "total_stars": total_stars,
                "review_min_distinct": review_min,
                "strong_min_distinct": strong_min,
                "review_min_total_stars": review_stars,
                "strong_min_total_stars": strong_stars,
                "protection_level": level,
            }
        )

    return {
        "skills": grouped,
        "packages": packages,
        "neutral_probability_model": {
            "inspiration_event_count": event_count,
            "uses_affinity": False,
            "direct_white_base_proc_rates": white_rates,
            "race_granted_skill_base_proc_rates": race_rates,
        },
    }


def _skill_is_preserved(
    candidate: dict[str, Any],
    replacement: dict[str, Any] | None,
    protection_config: dict[str, Any],
    *,
    require_direct: bool,
) -> tuple[bool, list[str]]:
    if not replacement:
        return False, ["missing_skill"]
    ratio = float(protection_config.get("replacement_probability_ratio", 0.90))
    tolerance = float(
        protection_config.get("replacement_probability_tolerance", 0.01)
    )
    deficits: list[str] = []
    candidate_probability = float(candidate.get("neutral_probability") or 0.0)
    replacement_probability = float(replacement.get("neutral_probability") or 0.0)
    required_probability = max(0.0, candidate_probability * ratio - tolerance)
    if replacement_probability + 1e-12 < required_probability:
        deficits.append("neutral_probability")
    if require_direct:
        candidate_direct = float(
            candidate.get("direct_neutral_probability") or 0.0
        )
        replacement_direct = float(
            replacement.get("direct_neutral_probability") or 0.0
        )
        required_direct = max(0.0, candidate_direct * ratio - tolerance)
        if not replacement.get("direct") or replacement_direct + 1e-12 < required_direct:
            deficits.append("direct_future_gp_source")
    return not deficits, deficits


def compare_spark_heritage(
    candidate_heritage: dict[str, Any] | None,
    replacement_heritage: dict[str, Any] | None,
    protection_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare protected inheritance assets and return a verdict floor."""
    config = protection_config or {}
    if not bool(config.get("enabled", False)) or not candidate_heritage:
        return {
            "applied": False,
            "verdict_floor": None,
            "primary_reason_code": None,
            "reason_codes": [],
            "protected_skills": [],
            "deficits": [],
            "package_comparisons": [],
        }

    candidate_skills = candidate_heritage.get("skills") or {}
    replacement_skills = (replacement_heritage or {}).get("skills") or {}
    protected_skills: list[dict[str, Any]] = []
    deficits: list[dict[str, Any]] = []

    for key, candidate in candidate_skills.items():
        signals = list(candidate.get("protection_signals") or [])
        if not signals:
            continue
        replacement = replacement_skills.get(key)
        require_direct = any(
            signal.get("reason_code") == "protected_direct_future_gp_spark"
            for signal in signals
        )
        preserved, metric_deficits = _skill_is_preserved(
            candidate, replacement, config, require_direct=require_direct
        )
        comparison = {
            "catalog_key": key,
            "name": candidate.get("name") or key,
            "signals": signals,
            "candidate": _compact_skill(candidate),
            "replacement": _compact_skill(replacement),
            "preserved_by_replacement": preserved,
            "metric_deficits": metric_deficits,
        }
        protected_skills.append(comparison)
        if preserved:
            continue
        reason_codes = list(
            dict.fromkeys(str(signal.get("reason_code")) for signal in signals)
        )
        floor = (
            LIKELY_KEEP
            if any(signal.get("strength") == LIKELY_KEEP for signal in signals)
            else REVIEW
        )
        deficits.append(
            {
                "kind": "skill",
                **comparison,
                "reason_codes": reason_codes,
                "verdict_floor": floor,
            }
        )

    candidate_packages = {
        str(package.get("key")): package
        for package in candidate_heritage.get("packages") or []
        if package.get("key")
    }
    replacement_packages = {
        str(package.get("key")): package
        for package in (replacement_heritage or {}).get("packages") or []
        if package.get("key")
    }
    package_comparisons: list[dict[str, Any]] = []
    for key, candidate in candidate_packages.items():
        candidate_level = candidate.get("protection_level")
        if candidate_level not in {REVIEW, LIKELY_KEEP}:
            continue
        replacement = replacement_packages.get(key) or {}
        replacement_level = replacement.get("protection_level")
        candidate_present = list(candidate.get("present_skills") or [])
        replacement_present = set(replacement.get("present_skills") or [])
        missing_skills = [
            skill_key for skill_key in candidate_present if skill_key not in replacement_present
        ]
        degraded_skills: list[str] = []
        for skill_key in candidate_present:
            if skill_key in missing_skills:
                continue
            preserved, _metrics = _skill_is_preserved(
                candidate_skills.get(skill_key) or {},
                replacement_skills.get(skill_key),
                config,
                require_direct=False,
            )
            if not preserved:
                degraded_skills.append(skill_key)

        structural_loss = bool(
            missing_skills
            or (
                candidate_level == LIKELY_KEEP
                and replacement_level != LIKELY_KEEP
            )
            or (
                candidate_level == REVIEW
                and replacement_level not in {REVIEW, LIKELY_KEEP}
            )
        )
        quality_loss = bool(degraded_skills)
        preserved = not structural_loss and not quality_loss
        reason_code = (
            "protected_package_not_preserved_by_replacement"
            if structural_loss
            else "protected_important_skill_set"
        )
        comparison = {
            "key": key,
            "label": candidate.get("label") or key,
            "candidate_level": candidate_level,
            "replacement_level": replacement_level,
            "candidate_distinct_count": int(candidate.get("distinct_count") or 0),
            "replacement_distinct_count": int(replacement.get("distinct_count") or 0),
            "candidate_total_stars": int(candidate.get("total_stars") or 0),
            "replacement_total_stars": int(replacement.get("total_stars") or 0),
            "candidate_skills": candidate_present,
            "replacement_skills": list(replacement.get("present_skills") or []),
            "missing_skills": missing_skills,
            "degraded_skills": degraded_skills,
            "preserved_by_replacement": preserved,
        }
        package_comparisons.append(comparison)
        if preserved:
            continue
        floor = candidate_level if structural_loss else REVIEW
        deficits.append(
            {
                "kind": "package",
                **comparison,
                "reason_codes": [reason_code],
                "verdict_floor": floor,
            }
        )

    reason_priority = {
        "protected_direct_future_gp_spark": 0,
        "protected_hard_to_obtain_spark": 1,
        "protected_package_not_preserved_by_replacement": 2,
        "protected_repeated_white_spark": 3,
        "protected_important_skill_set": 4,
    }
    reason_codes = sorted(
        {
            reason
            for deficit in deficits
            for reason in deficit.get("reason_codes") or []
        },
        key=lambda reason: (reason_priority.get(reason, 99), reason),
    )
    verdict_floor = (
        LIKELY_KEEP
        if any(deficit.get("verdict_floor") == LIKELY_KEEP for deficit in deficits)
        else REVIEW
        if deficits
        else None
    )
    protected_skills.sort(
        key=lambda item: (
            not bool(item.get("preserved_by_replacement")),
            float((item.get("candidate") or {}).get("max_context_weight") or 0.0),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )
    return {
        "applied": bool(deficits),
        "verdict_floor": verdict_floor,
        "primary_reason_code": reason_codes[0] if reason_codes else None,
        "reason_codes": reason_codes,
        "protected_skills": protected_skills,
        "deficits": deficits,
        "package_comparisons": package_comparisons,
    }

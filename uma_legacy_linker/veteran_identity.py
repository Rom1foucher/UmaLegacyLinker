from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Mapping


def format_rank_score(value: object, missing: str = "—") -> str:
    """Format an in-game evaluation score without losing a real zero."""

    if value is None or value == "":
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return missing
    if number.is_integer():
        return f"{int(number):,}".replace(",", " ")
    return f"{number:,.2f}".replace(",", " ").rstrip("0").rstrip(".")


def veteran_name(identity: Mapping[str, Any] | None) -> str:
    identity = identity or {}
    return str(identity.get("card_name") or identity.get("uma_name") or "—")


def canonical_veteran_label(identity: Mapping[str, Any] | None) -> str:
    """Return the one user-facing identity: card name followed by score."""

    identity = identity or {}
    name = veteran_name(identity)
    if identity.get("rank_score") is None or identity.get("rank_score") == "":
        return name
    return f"{name} · {format_rank_score(identity.get('rank_score'))}"


def technical_veteran_tooltip(identity: Mapping[str, Any] | None) -> str:
    """Keep the stable local key available without promoting it as a name."""

    identity = identity or {}
    trained_id = identity.get("trained_chara_id")
    return "" if trained_id is None or trained_id == "" else f"#{trained_id}"


def _blue_star_total(identity: Mapping[str, Any]) -> int:
    sparks = identity.get("sparks") or {}
    if not isinstance(sparks, Mapping):
        return 0
    factors = (sparks.get("by_type") or {}).get("blue_stat") or []
    return sum(
        int(factor.get("stars") or 0)
        for factor in factors
        if isinstance(factor, Mapping)
    )


def canonical_veteran_labels(
    identities: Iterable[Mapping[str, Any]],
    *,
    rank_label: str = "rank",
    blue_label: str = "Blue",
) -> list[str]:
    """Disambiguate genuine name/score collisions without exposing local IDs."""

    items = list(identities)
    labels = [canonical_veteran_label(item) for item in items]
    counts = Counter(labels)
    resolved = list(labels)
    for label, count in counts.items():
        if count < 2:
            continue
        indexes = [index for index, value in enumerate(labels) if value == label]
        ranks = [str(items[index].get("rank") or "").strip() for index in indexes]
        if all(ranks) and len(set(ranks)) == len(ranks):
            for index, rank in zip(indexes, ranks):
                resolved[index] = f"{label} · {rank_label} {rank}"
            continue
        blue_totals = [_blue_star_total(items[index]) for index in indexes]
        if len(set(blue_totals)) == len(blue_totals):
            for index, total in zip(indexes, blue_totals):
                resolved[index] = f"{label} · {total}★ {blue_label}"
    return resolved


def game_rank_label(value: object) -> str:
    """Decode the exported game rank; never invent a missing score."""
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return '—'
    labels = ['G', 'G+', 'F', 'F+', 'E', 'E+', 'D', 'D+', 'C', 'C+',
              'B', 'B+', 'A', 'A+', 'S', 'S+', 'SS', 'SS+']
    if 1 <= rank <= len(labels):
        return labels[rank - 1]
    index = rank - 19
    families = ['UG', 'UF', 'UE', 'UD', 'UC', 'UB', 'UA', 'US']
    if 0 <= index < 10 * len(families):
        family, suffix = divmod(index, 10)
        return families[family] + (str(suffix) if suffix else '')
    return '—'


def game_veteran_label(identity: Mapping[str, Any] | None) -> str:
    identity = identity or {}
    return f"{veteran_name(identity)} · {game_rank_label(identity.get('rank'))} · {format_rank_score(identity.get('rank_score'))}"

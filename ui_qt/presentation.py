from __future__ import annotations

from html import escape
from typing import Any

from uma_legacy_linker.i18n import profile_label, translate_text
from ui_qt.lineage_nodes import build_result_lineage_nodes
from ui_qt.theme import (
    COLORS,
    RANK_BADGE_COLORS,
    SPARK_COLORS,
    spark_semantic_label,
    spark_style_key,
)
from ui_qt.typography import TYPE_SCALE_PT, css_point_size
from uma_legacy_linker.veteran_identity import (
    canonical_veteran_label,
    canonical_veteran_labels,
    format_rank_score,
    veteran_name,
)


COMPONENT_LABELS = {
    "affinity": "Affinité",
    "g1_potential": "Potentiel G1",
    "blue": "Bleues",
    "distance_s": "Support Distance S",
    "pink_other": "Autres roses",
    "pink": "Roses",
    "white_skill": "Whites propres",
    "white_generation": "Bonus de lignée white",
    "race_scenario": "Race Sparks",
    "unique": "Vertes / uniques",
}

DISTANCE_STATUS = {
    "ready_for_s": "Prête pour S",
    "distance_b_compensated": "B compensée",
    "distance_b_uncompensated": "B non compensée",
    "no_s_support": "A sans support S",
    "underprepared": "Sous-préparée",
    "non_viable": "Non viable",
    "fragile": "Fragile",
    "viable": "Viable",
    "strong": "Forte",
    "excellent": "Excellente",
    "deficit": "Déficit",
    "light": "Légère",
    "balanced": "Équilibrée",
    "distance_carrier": "Porteuse distance",
}


# Palette locale du panneau de diagnostic.  Elle reprend le thème Qt mais reste
# indépendante : le rendu se fait dans un QTextDocument qui ne voit pas la
# feuille de style de l'application.
PANEL = {
    "text": "#e9f1fb",
    "text_soft": "#c3d2e4",
    "muted": "#8b9db5",
    "faint": "#6f8199",
    "surface": "#16202e",
    "surface_alt": "#111a26",
    "surface_deep": "#0d151f",
    "border": COLORS["border"],
    "border_soft": "#1d2939",
    "accent": "#6fdcb8",
    "accent_soft": "#8af0d0",
    "pink": "#ff9dbb",
    "gold": "#f4d179",
}

FONT_SIZE = {
    role: css_point_size(role)
    for role in TYPE_SCALE_PT
}


def _t(text: object, language: str) -> str:
    return str(translate_text(str(text), language))


def _section(title: str) -> str:
    """Titre de section : filet d'accent + libellé, avec un rythme constant."""
    return (
        "<table class='section-head' width='100%' cellspacing='0' cellpadding='0'><tr>"
        f"<td class='section-mark' width='3' bgcolor='{PANEL['accent']}' "
        f"style='background-color:{PANEL['accent']};'>&nbsp;</td>"
        f"<td class='section-title'>{escape(str(title))}</td>"
        "</tr></table>"
    )


def _number(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _percent(value: object, digits: int = 1) -> str:
    try:
        return f"{100 * float(value):.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _identity_name(identity: dict[str, Any] | None) -> str:
    return veteran_name(identity)


def _identity_meta(identity: dict[str, Any] | None) -> str:
    """Return optional score metadata; technical IDs stay out of the surface."""
    identity = identity or {}
    rank_score = identity.get("rank_score")
    if rank_score is None or rank_score == "":
        return ""
    return format_rank_score(rank_score)


def _identity(identity: dict[str, Any] | None) -> str:
    return canonical_veteran_label(identity)


def profile_summary(profile: dict[str, Any] | None, language: str) -> str:
    profile = profile or {}
    values = []
    for kind in ("surface", "distance", "style"):
        code = str(profile.get(kind) or "")
        if code:
            values.append(profile_label(kind, code, language))
    return " · ".join(values) or "—"


def distance_status(row: dict[str, Any], language: str) -> str:
    key = str((row.get("distance_viability") or {}).get("key") or "")
    return _t(DISTANCE_STATUS.get(key, key or "—"), language)


def _rank_badge(rank: object, *, large: bool = False) -> str:
    value = str(rank or "—").upper()
    css_class = value if value in RANK_BADGE_COLORS else "unknown"
    background, border, foreground = RANK_BADGE_COLORS[css_class]
    width = 38 if large else 29
    font_size = FONT_SIZE["brand" if large else "section"]
    return (
        "<table class='rank-badge-table' cellspacing='0' cellpadding='0'>"
        "<tr>"
        f"<td class='rank rank-{css_class}' width='{width}' "
        f"style='color:{foreground}; background-color:{background}; "
        f"border:1px solid {border}; padding:3px 5px; "
        f"font-size:{font_size}; font-weight:900; font-style:italic; "
        "text-align:center;'>"
        f"{escape(value)}</td>"
        "</tr></table>"
    )


def _metric_cell(
    label: str,
    value: str,
    accent: str,
    value_class: str,
    *,
    rank: str | None = None,
) -> str:
    badge = (
        f"<td class='metric-badge' width='38'>{_rank_badge(rank)}</td>" if rank else ""
    )
    content = (
        "<table class='metric-content' width='100%' cellspacing='0' cellpadding='0'><tr>"
        f"{badge}"
        f"<td class='metric-copy'>"
        f"<span class='metric-label' style='color:{accent};'>"
        f"{escape(label.upper())}</span><br>"
        f"<span class='metric-value {value_class}'>{escape(value)}</span>"
        "</td>"
        "</tr></table>"
    )
    return (
        "<td class='metric-card' width='33%' "
        f"bgcolor='{PANEL['surface']}' "
        f"style='background-color:{PANEL['surface']}; "
        f"border:1px solid {PANEL['border']}; "
        "padding:10px 13px 11px 13px; vertical-align:middle;'>"
        f"{content}</td>"
    )


def _metric_strip(row: dict[str, Any], kind: str, language: str) -> str:
    score = _number(row.get("score"), 2)
    affinity = row.get("affinity") or {}
    if kind == "future":
        second_label = _t("Contribution affinité", language)
        second_value = _number(row.get("affinity_raw"), 0)
        third_label = _t("G1 différentes", language)
        third_value = str(int(row.get("g1_count") or 0))
        rank = ""
    elif kind == "grandparent_pair":
        final_affinity = (
            row.get("final_parent_affinity")
            or row.get("final_branch_affinity")
            or {}
        )
        second_label = _t("Potentiel final", language)
        second_value = _number(
            final_affinity.get("potential_total", final_affinity.get("total")),
            0,
        )
        third_label = _t("G1 communes", language)
        third_value = str(int(final_affinity.get("common_g1_count") or 0))
        rank = ""
    else:
        second_label = _t("Affinité", language)
        second_value = _number(
            affinity.get("total") if isinstance(affinity, dict) else row.get("affinity_raw"),
            0,
        )
        third_label = "P(S)"
        probability_reach_s = (row.get("distance_s_summary") or {}).get(
            "probability_reach_s"
        )
        third_value = _percent(probability_reach_s)
        rank = "S" if probability_reach_s is not None else ""
    score_cell = _metric_cell(
        _t("Score de lignée", language),
        score,
        PANEL["accent"],
        "score-value",
    )
    affinity_cell = _metric_cell(
        second_label,
        second_value,
        PANEL["pink"],
        "affinity-value",
    )
    third_cell = _metric_cell(
        third_label,
        third_value,
        PANEL["gold"],
        "rank-value",
        rank="S" if rank else None,
    )
    return (
        "<table class='metric-row' width='100%' cellspacing='7' cellpadding='0'><tr>"
        + score_cell
        + affinity_cell
        + third_cell
        + "</tr></table>"
    )


def _share_bar(ratio: float) -> str:
    """Barre de contribution.  Les pourcentages de largeur sont la seule mise en
    forme proportionnelle que Qt sait rendre de façon fiable."""
    filled = max(2, min(100, int(round(100 * ratio))))
    rest = 100 - filled
    remainder = (
        f"<td width='{rest}%' height='5' bgcolor='{PANEL['surface_deep']}' "
        f"style='background-color:{PANEL['surface_deep']}; height:5px;'></td>"
        if rest > 0
        else ""
    )
    return (
        "<table class='share-bar' width='100%' cellspacing='0' cellpadding='0'><tr>"
        f"<td width='{filled}%' height='5' bgcolor='{PANEL['accent']}' "
        f"style='background-color:{PANEL['accent']}; height:5px;'></td>"
        f"{remainder}</tr></table>"
    )


def _component_table(row: dict[str, Any], language: str) -> str:
    breakdown = row.get("score_breakdown") or {}
    entries = breakdown.get("components") or {}
    points_by_key: dict[str, float] = {}
    for key, item in entries.items():
        if not isinstance(item, dict):
            continue
        try:
            points_by_key[str(key)] = float(item.get("points") or 0.0)
        except (TypeError, ValueError):
            points_by_key[str(key)] = 0.0
    peak = max(points_by_key.values(), default=0.0)
    body = []
    for key, item in entries.items():
        if not isinstance(item, dict):
            continue
        label = _t(COMPONENT_LABELS.get(str(key), str(key)), language)
        score = _number(item.get("component_score"), 2)
        weight = _percent(item.get("weight"), 1)
        points = _number(item.get("points"), 2)
        ratio = (points_by_key.get(str(key), 0.0) / peak) if peak > 0 else 0.0
        body.append(
            f"<tr><td class='component-name'>{escape(label)}</td>"
            f"<td align='right'>{score}</td>"
            f"<td align='right'>{weight}</td>"
            f"<td align='right' class='component-points'><b>{points}</b></td>"
            f"<td class='component-bar' width='88'>{_share_bar(ratio)}</td></tr>"
        )
    if not body:
        for key, value in (row.get("components") or {}).items():
            label = _t(COMPONENT_LABELS.get(str(key), str(key)), language)
            body.append(
                f"<tr><td class='component-name'>{escape(label)}</td>"
                f"<td colspan='4' align='right'>{_number(value, 2)}</td></tr>"
            )
    return (
        "<table class='component-table' width='100%' cellspacing='0' cellpadding='0'>"
        "<thead><tr>"
        f"<th>{escape(_t('Composante', language).upper())}</th>"
        f"<th align='right'>{escape(_t('Brut', language).upper())}</th>"
        f"<th align='right'>{escape(_t('Poids', language).upper())}</th>"
        f"<th align='right'>{escape(_t('Points', language).upper())}</th>"
        "<th width='88'>&nbsp;</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _facts_table(items: list[tuple[str, object]]) -> str:
    rows = []
    last = len(items) - 1
    for index, (label, value) in enumerate(items):
        css = " class='facts-last'" if index == last else ""
        rows.append(
            f"<tr><th{css}>{escape(str(label))}</th>"
            f"<td{css} align='right'><b>{escape(str(value))}</b></td></tr>"
        )
    return (
        "<table class='facts-table' width='100%' cellspacing='0' cellpadding='0'>"
        + "".join(rows)
        + "</table>"
    )


def _g1_plan(row: dict[str, Any]) -> dict[str, Any]:
    plan = (
        row.get("race_affinity_plan")
        or (row.get("affinity") or {}).get("race_affinity_plan")
        or (row.get("final_parent_affinity") or {}).get("race_affinity_plan")
        or (row.get("final_branch_affinity") or {}).get("race_affinity_plan")
        or {}
    )
    return plan if isinstance(plan, dict) else {}


def _g1_plan_block(
    row: dict[str, Any],
    language: str,
    *,
    left_name: str,
    right_name: str,
) -> str:
    plan = _g1_plan(row)
    if not plan or not plan.get("races"):
        return ""

    shared_bonus = int(plan.get("shared_race_bonus") or 6)
    one_side_bonus = int(plan.get("one_side_race_bonus") or 3)

    def names(key: str) -> str:
        values = [str(value) for value in plan.get(key) or [] if str(value).strip()]
        return " · ".join(values) if values else _t("Aucune", language)

    rows = (
        (
            _t("G1 communes (+{bonus})", language).replace(
                "{bonus}", str(shared_bonus)
            ),
            names("common_g1_names"),
        ),
        (
            _t("{name} uniquement (+{bonus})", language)
            .replace("{name}", left_name)
            .replace("{bonus}", str(one_side_bonus)),
            names("left_only_g1_names"),
        ),
        (
            _t("{name} uniquement (+{bonus})", language)
            .replace("{name}", right_name)
            .replace("{bonus}", str(one_side_bonus)),
            names("right_only_g1_names"),
        ),
    )
    objective_races = [
        str(race.get("name") or "")
        for race in plan.get("objective_races") or []
        if isinstance(race, dict) and str(race.get("name") or "").strip()
    ]
    if objective_races:
        target = plan.get("target") or {}
        target_name = _identity_name(target if isinstance(target, dict) else {})
        rows += (
            (
                _t("Objectifs obligatoires de {name}", language).replace(
                    "{name}",
                    target_name,
                ),
                " · ".join(objective_races),
            ),
        )
    body = "".join(
        "<tr>"
        f"<th>{escape(label)}</th>"
        f"<td>{escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )
    variants = plan.get("schedule_variants") or {}
    standard = (
        variants.get("standard")
        if isinstance(variants, dict) and isinstance(variants.get("standard"), dict)
        else plan
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
    below_cutoff = [
        str(race.get("name") or "")
        for race in standard.get("races") or []
        if isinstance(race, dict)
        and race.get("planning_status") == "below_win_cutoff"
        and str(race.get("name") or "").strip()
    ]
    if below_cutoff:
        rows += (
            (
                _t("G1 exclues par le seuil de victoire", language),
                " · ".join(below_cutoff),
            ),
        )
        body = "".join(
            "<tr>"
            f"<th>{escape(label)}</th>"
            f"<td>{escape(value)}</td>"
            "</tr>"
            for label, value in rows
        )
    facts: list[tuple[str, object]] = [
        (
            _t("Bonus optimal avec objectifs", language),
            f"+{int(standard.get('optimal_bonus') or 0)}",
        ),
        (
            _t("G1 d’affinité planifiées", language),
            int(
                standard.get("optimal_affinity_race_count")
                or standard.get("optimal_race_count")
                or 0
            ),
        ),
        (
            _t("Courses d’objectif planifiées", language),
            int(standard.get("scheduled_objective_race_count") or 0),
        ),
        (
            _t("Conflits G1 / objectifs", language),
            objective_conflicts,
        ),
        (
            _t("Série maximale", language),
            int((standard.get("streaks") or {}).get("max_consecutive") or 0),
        ),
    ]
    cutoff = plan.get("g1_win_probability_cutoff")
    if cutoff is not None:
        facts.append(
            (
                _t("Seuil de victoire Independent Training", language),
                f"{100.0 * float(cutoff):.0f}%",
            )
        )
    if trackblazer:
        facts.append(
            (
                _t("Bonus optimal Trackblazer", language),
                f"+{int(trackblazer.get('optimal_bonus') or 0)}",
            )
        )
    summary = _facts_table(facts)
    return (
        summary
        + "<table class='factor-table' width='100%' cellspacing='0' cellpadding='0'>"
        + body
        + "</table>"
    )


def _distance_block(row: dict[str, Any], language: str) -> str:
    detail = row.get("distance_s_summary") or {}
    if not detail:
        return ""
    viability = row.get("distance_viability") or detail.get("viability") or {}
    status = distance_status(row, language)
    items = [
        (_t("Statut", language), f"{status} · {_t('palier', language)} {viability.get('tier', 0)}"),
        (
            _t("Support", language),
            f"{detail.get('total_stars', 0)}★ · "
            f"{detail.get('carrier_count', 0)} {_t('porteur(s)', language)} · "
            f"{detail.get('parent_carrier_count', 0)} {_t('direct(s)', language)}",
        ),
        (
            _t("Procs requis", language),
            f"A  {detail.get('procs_required_for_a', 0)}"
            f"   ·   S  {detail.get('procs_required_for_s', 0)}",
        ),
    ]
    return _facts_table(items)


def _rank_transition(base: str, initial: str) -> str:
    if base == initial:
        return _rank_badge(initial)
    return (
        "<table class='rank-transition' cellspacing='4' cellpadding='0'><tr>"
        f"<td>{_rank_badge(base)}</td>"
        "<td class='rank-arrow' width='20'>&rarr;</td>"
        f"<td>{_rank_badge(initial)}</td>"
        "</tr></table>"
    )


def _s_chance(probability: object) -> str:
    try:
        value = float(probability or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value <= 0:
        return "<span class='no-chance'>&mdash;</span>"
    # Le badge « S » est déjà porté par l'en-tête de colonne : seule la valeur
    # reste, ce qui évite une colonne surchargée sur trois lignes.
    css = "s-chance-strong" if value >= 0.35 else "s-chance-value"
    return f"<span class='{css}'>{escape(_percent(probability))}</span>"


def _aptitude_block(
    row: dict[str, Any],
    language: str,
    profile: dict[str, Any] | None = None,
) -> str:
    pink_details = ((row.get("component_details") or {}).get("pink") or {})
    dimensions = row.get("aptitude_summaries") or pink_details.get("dimensions") or {}
    distance = row.get("distance_s_summary") or pink_details.get("distance_s") or {}
    profile = profile or {}
    rows = []
    for key, label in (
        ("surface", "Terrain"),
        ("distance", "Distance"),
        ("style", "Style"),
    ):
        detail = distance if key == "distance" else dimensions.get(key) or {}
        if not detail:
            continue
        code = str(profile.get(key) or "")
        target = profile_label(key, code, language) if code else _t(label, language)
        base = str(detail.get("base_rank_label") or "—")
        initial = str(detail.get("initial_rank_label") or base)
        transition = _rank_transition(base, initial)
        chance = _s_chance(detail.get("probability_reach_s"))
        rows.append(
            "<tr>"
            f"<th width='22%'>{escape(_t(label, language))}</th>"
            f"<td class='aptitude-name' width='34%'>{escape(target)}</td>"
            f"<td class='aptitude-ranks' width='26%' align='center'>{transition}</td>"
            f"<td class='aptitude-chance' width='18%' align='right'>{chance}</td>"
            "</tr>"
        )
    if not rows:
        return ""
    return (
        "<table class='aptitude-table' width='100%' cellspacing='0' cellpadding='0'>"
        "<tr class='aptitude-heading'>"
        f"<th width='22%'>{escape(_t('Aptitude', language).upper())}</th>"
        f"<th width='34%'>{escape(_t('Cible', language).upper())}</th>"
        f"<th width='26%' align='center'>{escape(_t('Départ', language).upper())}</th>"
        f"<th width='18%' align='right'>{escape(_t('Chance S', language).upper())}</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )


_SPARK_FAMILY_ORDER = ("blue", "pink", "green", "other")


def _spark_family(factor_type: str) -> str:
    if factor_type == "blue_stat":
        return "blue"
    if factor_type == "red_aptitude":
        return "pink"
    if factor_type == "unique":
        return "green"
    return "other"


def _spark_recap_branches(
    nodes: dict[str, dict[str, Any]],
    mode: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if mode in {"pair", "online_parent"}:
        return (
            ("p1", ("p1", "p1-1", "p1-2")),
            ("p2", ("p2", "p2-1", "p2-2")),
        )
    if mode == "branch":
        return (("p1", ("p1", "p1-1", "p1-2")),)
    positions = ("p1",) if mode == "future" else ("p1", "p2")
    return tuple((position, (position,)) for position in positions if nodes.get(position))


def _spark_branch_entries(
    nodes: dict[str, dict[str, Any]],
    direct_position: str,
    positions: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {
        family: [] for family in _SPARK_FAMILY_ORDER
    }
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for position in positions:
        node = nodes.get(position) or {}
        for index, factor in enumerate(node.get("sparks") or []):
            if not isinstance(factor, dict):
                continue
            factor_type = str(factor.get("type") or "other")
            family = _spark_family(factor_type)
            name = str(factor.get("name") or "—")
            stars = max(0, int(factor.get("stars") or 0))
            # Blue, Pink and White Sparks are condensed by name across the
            # three-member branch. Greens remain individual because the
            # costume carrying each unique is useful information on its own.
            if family in {"blue", "pink", "other"}:
                key = (family, factor_type, name.casefold())
            else:
                key = (family, position, f"{index}:{name.casefold()}")
            entry = merged.get(key)
            if entry is None:
                entry = {
                    "family": family,
                    "type": factor_type,
                    "name": name,
                    "stars": 0,
                    "copy_count": 0,
                    "is_direct": False,
                    "is_score_priority": False,
                    "is_score_useful": False,
                    "score_priority_rank": 999,
                    "failure_probability": 1.0,
                    "has_probability": False,
                }
                merged[key] = entry
                grouped[family].append(entry)
            entry["stars"] += stars
            entry["copy_count"] += 1
            entry["is_direct"] = bool(entry["is_direct"] or position == direct_position)
            entry["is_score_priority"] = bool(
                entry["is_score_priority"] or factor.get("is_score_priority")
            )
            entry["is_score_useful"] = bool(
                entry["is_score_useful"] or factor.get("is_score_useful")
            )
            try:
                entry["score_priority_rank"] = min(
                    int(entry["score_priority_rank"]),
                    int(factor.get("score_priority_rank") or 999),
                )
            except (TypeError, ValueError):
                pass
            probability = factor.get("proc_probability_over_run")
            if probability is not None and family == "other":
                try:
                    normalised = max(0.0, min(float(probability), 1.0))
                except (TypeError, ValueError):
                    continue
                # Probabilité qu'au moins un porteur de la branche fasse procer
                # la skill sur la run : on compose les échecs, comme le moteur
                # de score le fait par skill distincte.
                entry["failure_probability"] *= 1.0 - normalised
                entry["has_probability"] = True

    for family in _SPARK_FAMILY_ORDER:
        grouped[family].sort(
            key=lambda item: (
                int(item.get("score_priority_rank") or 999),
                not bool(item.get("is_direct")),
                -int(item.get("stars") or 0),
                str(item.get("name") or "").casefold(),
            )
        )
    return grouped


def _spark_probability_text(entry: dict[str, Any]) -> str:
    """Probabilité cumulée de proc sur la run, pour la branche du parent.

    Plusieurs porteurs de la même skill dans une branche tirent indépendamment :
    la probabilité qu'au moins un proc soit obtenu vaut 1 - Π(1 - p_i). La
    fourchette min–max affichée auparavant sous-estimait donc le vrai total.
    """
    if not entry.get("has_probability"):
        return ""
    failure = max(0.0, min(float(entry.get("failure_probability") or 1.0), 1.0))
    return f"{100 * (1.0 - failure):.2f}%"


def _spark_card(entry: dict[str, Any], language: str) -> str:
    style_key = spark_style_key(entry)
    background, border, foreground = SPARK_COLORS.get(style_key, SPARK_COLORS["other"])
    semantic_label = _t(spark_semantic_label(entry), language)
    marker = (
        "<span class='parent-marker'>P</span>&nbsp;"
        if entry.get("is_direct")
        else ""
    )
    copies = int(entry.get("copy_count") or 0)
    copy_text = f" ×{copies}" if copies > 1 else ""
    probability_text = _spark_probability_text(entry)
    metadata = []
    if copy_text:
        metadata.append(copy_text.strip())
    if probability_text:
        metadata.append(probability_text)
    meta = " · ".join(metadata)
    meta_cell = (
        f"<td class='spark-meta' align='right'>{escape(meta)}</td>"
        if meta
        else "<td class='spark-meta'>&nbsp;</td>"
    )
    # Une seule ligne par spark : étoiles, nom, puis méta calée à droite.  Le
    # cadre coloré est remplacé par un filet d'accent, beaucoup moins bruyant
    # quand une trentaine de chips sont empilées.
    return (
        "<table class='spark-card' width='100%' cellspacing='0' cellpadding='0' "
        f"bgcolor='{background}' style='background-color:{background};'>"
        "<tr>"
        f"<td class='spark-accent' width='3' bgcolor='{border}' "
        f"style='background-color:{border};'>&nbsp;</td>"
        f"<td class='spark-stars' width='68' style='color:{foreground};'>"
        f"{marker}<b>{int(entry.get('stars') or 0)}★</b></td>"
        f"<td class='spark-name' style='color:{foreground};'>"
        f"<span class='spark-kind'>[{escape(semantic_label)}]</span>&nbsp;"
        f"{escape(str(entry.get('name') or '—'))}</td>"
        f"{meta_cell}</tr></table>"
    )


def _spark_grid(entries: list[dict[str, Any]], language: str) -> str:
    rows = []
    for index in range(0, len(entries), 2):
        cells = []
        for entry in entries[index:index + 2]:
            cells.append(
                "<td class='spark-grid-cell' width='50%' valign='top'>"
                + _spark_card(entry, language)
                + "</td>"
            )
        if len(cells) == 1:
            cells.append("<td class='spark-grid-cell' width='50%'>&nbsp;</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table class='spark-grid' width='100%' cellspacing='5' cellpadding='0'>"
        + "".join(rows)
        + "</table>"
    )


def _spark_recap(row: dict[str, Any], mode: str, language: str) -> str:
    nodes = build_result_lineage_nodes(None, row, mode)
    groups: list[str] = []
    branches = _spark_recap_branches(nodes, mode)
    is_aggregated = mode in {"pair", "online_parent", "branch"}
    family_labels = {
        "blue": _t("Bleues", language),
        "pink": _t("Roses", language),
        "green": _t("Vertes", language),
        "other": _t("Reste", language),
    }
    for direct_position, positions in branches:
        direct_node = nodes.get(direct_position) or {}
        entries = _spark_branch_entries(nodes, direct_position, positions)
        if not any(entries.values()):
            continue
        rows = []
        for family in _SPARK_FAMILY_ORDER:
            family_entries = entries[family]
            if not family_entries:
                continue
            accent = SPARK_COLORS[
                {
                    "blue": "blue_stat",
                    "pink": "red_aptitude",
                    "green": "unique",
                    "other": "white_skill",
                }[family]
            ][2]
            rows.append(
                "<table class='spark-family' width='100%' cellspacing='0' cellpadding='0'>"
                "<tr>"
                f"<th style='color:{accent};'>{escape(family_labels[family])}"
                f"<span class='spark-count'>&nbsp;&nbsp;{len(family_entries)}</span></th>"
                "</tr></table>"
                + _spark_grid(family_entries, language)
            )
        name = str(direct_node.get("card_name") or direct_node.get("uma_name") or "—")
        visible_member_count = sum(1 for position in positions if nodes.get(position))
        if visible_member_count >= 3:
            scope = _t("Parent + ses deux parents", language)
        elif visible_member_count == 2:
            scope = _t("Parent + un parent", language)
        else:
            scope = _t("Sparks directs", language)
        groups.append(
            "<table class='spark-owner' width='100%' cellspacing='0' cellpadding='0'><tr>"
            f"<td><b>{escape(name)}</b></td>"
            f"<td class='spark-scope'>{escape(scope)}</td>"
            "</tr></table>"
            "<table class='spark-families' width='100%' cellspacing='0' cellpadding='0'><tr>"
            f"<td class='spark-families-body'>{''.join(rows)}</td>"
            "</tr></table>"
        )
    if not groups:
        return ""
    title = (
        _t("Résumé des Sparks par parent", language)
        if is_aggregated
        else _t("Récap des Sparks directs", language)
    )
    legend = ""
    if is_aggregated:
        legend = (
            "<p class='spark-legend'><span class='parent-marker'>P</span>&nbsp;"
            + escape(_t("présent sur le parent direct", language))
            + "&nbsp;·&nbsp;"
            + escape(_t("totaux Bleu/Rose/White sur la branche", language))
            + "&nbsp;·&nbsp;["
            + escape(_t("Priorité", language))
            + "] "
            + escape(_t("priorité majeure", language))
            + "&nbsp;·&nbsp;["
            + escape(_t("Utile", language))
            + "] "
            + escape(_t("white utile au profil", language))
            + "</p>"
        )
    return (
        _section(title)
        + legend
        + "<div class='spark-summary'>"
        + "".join(groups)
        + "</div>"
    )


def _top_factors(row: dict[str, Any], language: str) -> str:
    details = row.get("component_details") or {}
    groups = []
    for key in ("white_skill", "blue", "pink", "unique"):
        detail = details.get(key) or {}
        factors = detail.get("top_skills") or detail.get("top_factors") or detail.get("factors") or []
        names = []
        for factor in factors:
            if not isinstance(factor, dict) or not factor.get("name"):
                continue
            stars = int(factor.get("stars") or 0)
            names.append(f"{factor['name']}{f' {stars}★' if stars else ''}")
            if len(names) == 5:
                break
        if names:
            label = _t(COMPONENT_LABELS.get(key, key), language)
            groups.append(
                f"<tr><th>{escape(label)}</th>"
                f"<td>{escape(' · '.join(names))}</td></tr>"
            )
    if not groups:
        return ""
    return (
        "<table class='factor-table' width='100%' cellspacing='0' cellpadding='0'>"
        + "".join(groups)
        + "</table>"
    )


def _white_generation_block(row: dict[str, Any], language: str) -> str:
    """Render the engine's incremental White-generation diagnostics.

    ``lineage_generation_bonus`` is deliberately displayed as a gain in
    percentage points, not as an absolute generation chance and not as a final
    inheritance probability.
    """

    details = (row.get("component_details") or {}).get("white_generation") or {}
    if not isinstance(details, dict):
        return ""
    skills = [item for item in details.get("skills") or [] if isinstance(item, dict)]
    if not skills:
        return ""

    breakdown_components = ((row.get("score_breakdown") or {}).get("components") or {})
    included = "white_generation" in breakdown_components
    if details.get("included_in_weighted_score") is False:
        included = False
    score = (row.get("components") or {}).get("white_generation")
    if score is None:
        score = details.get("score")
    facts = [
        (_t("Support global de génération", language), f"{_number(score, 2)} / 100"),
        (_t("Sparks distinctes concernées", language), int(details.get("skill_count") or len(skills))),
        (_t("Inclus dans le score global", language), _t("Oui" if included else "Non", language)),
    ]

    rows = []
    for item in skills:
        name = str(item.get("name") or item.get("catalog_key") or "—")
        copies = max(0, int(item.get("lineage_copy_count") or 0))
        try:
            bonus = max(0.0, float(item.get("lineage_generation_bonus") or 0.0))
        except (TypeError, ValueError):
            bonus = 0.0
        rows.append(
            "<tr>"
            f"<td><b>{escape(name)}</b></td>"
            f"<td align='right'>×{copies}</td>"
            f"<td align='right' class='generation-gain'>+{100 * bonus:.2f} pts</td>"
            "</tr>"
        )

    try:
        per_copy = 100.0 * max(
            0.0, float(details.get("bonus_per_lineage_copy") or 0.0)
        )
    except (TypeError, ValueError):
        per_copy = 0.0
    explanation = _t(
        "Gain incrémental estimé pendant la run qui produit le parent : +{gain} points par porteur de la même White Skill. Ce n’est ni la probabilité totale de générer la Spark, ni sa probabilité de proc dans la run finale.",
        language,
    ).replace("{gain}", f"{per_copy:.2f}")

    return (
        _facts_table(facts)
        + "<table class='factor-table generation-table' width='100%' cellspacing='0' cellpadding='0'>"
        + "<thead><tr>"
        + f"<th>{escape(_t('Spark white', language).upper())}</th>"
        + f"<th align='right'>{escape(_t('Porteurs', language).upper())}</th>"
        + f"<th align='right'>{escape(_t('Gain de génération', language).upper())}</th>"
        + "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + "<p class='diagnostic-note'>"
        + escape(explanation)
        + "</p>"
    )


def _production_affinity_block(row: dict[str, Any], language: str) -> str:
    production = row.get("production_affinity") or {}
    if not isinstance(production, dict) or not production:
        return ""
    gp1 = production.get("gp1_inheritance_modifier") or {}
    gp2 = production.get("gp2_inheritance_modifier") or {}
    facts = [
        (_t("Affinité totale de la run", language), _number(production.get("total"), 1)),
        (_t("Coefficient individuel GP1", language), _number(gp1.get("total"), 1)),
        (_t("Coefficient individuel GP2", language), _number(gp2.get("total"), 1)),
        (_t("Valeur équilibrée", language), _number(production.get("scored_value"), 1)),
    ]
    return (
        _facts_table(facts)
        + "<p class='diagnostic-note'>"
        + escape(
            _t(
                "Diagnostic de la run intermédiaire qui fabrique le parent. Cette affinité n’est pas ajoutée au score de la lignée finale.",
                language,
            )
        )
        + "</p>"
    )


def _detail_styles() -> str:
    text = PANEL["text"]
    soft = PANEL["text_soft"]
    muted = PANEL["muted"]
    faint = PANEL["faint"]
    surface = PANEL["surface"]
    surface_alt = PANEL["surface_alt"]
    border = PANEL["border"]
    border_soft = PANEL["border_soft"]
    accent = PANEL["accent"]
    return f"""
    <style>
      body {{ color:{text}; font-size:{FONT_SIZE['body']}; line-height:1.45; }}
      h2 {{ margin:1px 0 4px 0; color:#f5f9ff; font-size:{FONT_SIZE['heading']}; font-weight:800; }}
      p {{ margin:7px 0; }}
      table {{ width:100%; border-collapse:collapse; }}
      .eyebrow {{ color:{accent}; font-weight:750; font-size:{FONT_SIZE['micro']}; }}
      .muted {{ color:{muted}; font-size:{FONT_SIZE['caption']}; }}
      .empty {{ color:{muted}; }}

      .section-head {{ margin:17px 0 7px 0; border-collapse:separate; }}
      .section-mark {{ padding:0; }}
      .section-title {{ color:#dce8f6; font-size:{FONT_SIZE['body']}; font-weight:750; padding:0 0 0 8px; }}

      .metric-row {{ border-collapse:separate; margin:13px 0 4px 0; }}
      .metric-card {{ text-align:left; }}
      .metric-content td {{ border:0; padding:0; vertical-align:middle; }}
      .metric-copy {{ text-align:left; }}
      .metric-badge {{ text-align:left; padding:0 10px 0 0; }}
      .metric-label {{ font-size:{FONT_SIZE['micro']}; font-weight:800; }}
      .metric-value {{ color:{text}; font-size:{FONT_SIZE['brand']}; font-weight:800; }}
      .score-value {{ color:#8af0d0; }}
      .affinity-value {{ color:#ff9dbb; }}
      .rank-value {{ color:#f4d179; }}

      .rank-badge-table {{ width:auto; border-collapse:separate; }}
      .rank-badge-table td {{ line-height:1; }}
      .rank-transition {{ width:auto; }}
      .rank-transition td {{ border:0; padding:0; background-color:transparent; vertical-align:middle; }}
      .rank-arrow {{ color:{faint}; text-align:center; font-size:{FONT_SIZE['body']}; }}

      .aptitude-table {{ margin:0 0 4px 0; border:1px solid {border}; }}
      .aptitude-table .aptitude-heading th {{ color:{muted}; background-color:{surface}; border-bottom:1px solid {border}; padding:7px 11px; font-size:{FONT_SIZE['micro']}; font-weight:800; text-align:left; }}
      .aptitude-table th {{ color:{muted}; background-color:{surface_alt}; border-bottom:1px solid {border_soft}; padding:7px 10px; font-size:{FONT_SIZE['caption']}; font-weight:650; text-align:left; }}
      .aptitude-table td {{ background-color:{surface_alt}; border-bottom:1px solid {border_soft}; padding:6px 10px; vertical-align:middle; }}
      .aptitude-name {{ color:{text}; font-size:{FONT_SIZE['body']}; font-weight:700; text-align:left; }}
      .aptitude-ranks {{ text-align:center; white-space:nowrap; }}
      .aptitude-chance {{ white-space:nowrap; }}
      .aptitude-table .rank-transition td {{ background-color:transparent; border:0; padding:0; }}
      .aptitude-table .rank-badge-table td {{ border:1px solid; padding:3px 5px; }}
      .s-chance-value {{ color:{soft}; font-size:{FONT_SIZE['body']}; font-weight:700; }}
      .s-chance-strong {{ color:#f4d179; font-size:{FONT_SIZE['body']}; font-weight:800; }}
      .no-chance {{ color:{faint}; }}

      .facts-table {{ margin:0 0 4px 0; }}
      .facts-table th {{ width:52%; color:{muted}; text-align:left; font-size:{FONT_SIZE['caption']}; font-weight:600; padding:6px 2px 6px 1px; border-bottom:1px solid {border_soft}; }}
      .facts-table td {{ color:{text}; font-size:{FONT_SIZE['body']}; padding:6px 1px 6px 2px; border-bottom:1px solid {border_soft}; }}
      .facts-table .facts-last {{ border-bottom:0; }}

      .component-table {{ margin:0 0 4px 0; }}
      .component-table th {{ color:{muted}; text-align:left; font-size:{FONT_SIZE['micro']}; font-weight:800; padding:6px 8px 6px 1px; border-bottom:1px solid {border}; }}
      .component-table td {{ color:{soft}; font-size:{FONT_SIZE['body']}; padding:6px 8px 6px 1px; border-bottom:1px solid {border_soft}; vertical-align:middle; }}
      .component-name {{ color:{text}; }}
      .component-points {{ color:#8af0d0; }}
      .component-bar {{ padding:7px 0 7px 10px; }}
      .share-bar {{ border-collapse:collapse; }}
      .share-bar td {{ padding:0; border:0; height:5px; }}

      .factor-table {{ margin:0 0 4px 0; }}
      .factor-table th {{ width:26%; color:{muted}; text-align:left; font-size:{FONT_SIZE['caption']}; font-weight:600; padding:6px 10px 6px 1px; border-bottom:1px solid {border_soft}; vertical-align:top; }}
      .factor-table td {{ color:{soft}; font-size:{FONT_SIZE['caption']}; padding:6px 1px; border-bottom:1px solid {border_soft}; vertical-align:top; }}

      .spark-summary {{ margin-top:2px; }}
      .spark-owner {{ margin:12px 0 0 0; background-color:{surface}; border:1px solid {border}; }}
      .spark-owner td {{ padding:7px 10px; color:{text}; font-size:{FONT_SIZE['body']}; }}
      .spark-owner .spark-scope {{ color:{muted}; text-align:right; font-size:{FONT_SIZE['micro']}; }}
      .spark-families {{ margin:0 0 4px 0; background-color:{surface_alt}; border:1px solid {border}; border-top:0; }}
      .spark-families-body {{ padding:6px 8px 7px 8px; }}
      .spark-family {{ margin:6px 0 2px 0; border-bottom:1px solid {border_soft}; }}
      .spark-family th {{ padding:4px 1px; text-align:left; font-size:{FONT_SIZE['micro']}; font-weight:800; }}
      .spark-count {{ color:{faint}; font-size:{FONT_SIZE['micro']}; font-weight:600; }}
      .spark-grid {{ width:100%; margin:2px 0 3px 0; border-collapse:separate; }}
      .spark-grid-cell {{ padding:0; border:0; }}
      .spark-card {{ width:100%; border-collapse:separate; }}
      .spark-card td {{ padding:4px 7px; border:0; vertical-align:middle; }}
      .spark-accent {{ padding:0; }}
      .spark-stars {{ white-space:nowrap; font-size:{FONT_SIZE['micro']}; }}
      .spark-name {{ font-size:{FONT_SIZE['caption']}; font-weight:650; text-align:left; }}
      .spark-kind {{ font-size:{FONT_SIZE['micro']}; font-weight:900; }}
      .spark-meta {{ color:{muted}; white-space:nowrap; font-size:{FONT_SIZE['micro']}; }}
      .generation-gain {{ color:{accent}; font-weight:750; }}
      .diagnostic-note {{ color:{muted}; font-size:{FONT_SIZE['micro']}; margin:6px 1px 9px 1px; }}
      .spark-legend {{ margin:2px 0 7px 0; color:{muted}; font-size:{FONT_SIZE['micro']}; }}
      .parent-marker {{ color:#140e02; background-color:#ffd36b; padding:1px 5px; font-size:{FONT_SIZE['caption']}; font-weight:900; }}
    </style>
    """


def result_detail_html(
    row: dict[str, Any] | None,
    kind: str,
    language: str,
    profile: dict[str, Any] | None = None,
) -> str:
    if not row:
        return f"<p class='empty'>{escape(_t('Sélectionne une ligne pour afficher le diagnostic.', language))}</p>"

    if kind == "pair":
        title = f"{_identity(row.get('parent_1'))} × {_identity(row.get('parent_2'))}"
        subtitle = _t("Paire finale", language)
    elif kind == "branch":
        title = _identity(row)
        subtitle = _t("Lignée candidate", language)
    else:
        title = _identity(row)
        subtitle = _t("Futur grand-parent", language)

    affinity = row.get("affinity") or {}
    if isinstance(affinity, dict):
        affinity_value = affinity.get("total", row.get("affinity_raw"))
        affinity_base = affinity.get("base")
        affinity_g1 = affinity.get("g1_bonus")
    else:
        affinity_value = row.get("affinity_raw")
        affinity_base = None
        affinity_g1 = None

    context = profile_summary(profile, language)
    html = f"""
    {_detail_styles()}
    <div class='eyebrow'>{escape(subtitle)}</div>
    <h2>{escape(title)}</h2>
    <div class='muted'>{escape(context)}</div>
    {_metric_strip(row, kind, language)}
    """
    if kind in {"pair", "branch"}:
        aptitude_html = _aptitude_block(row, language, profile)
        if aptitude_html:
            html += f"{_section(_t('Aptitudes — héritage visé', language))}"
            html += aptitude_html
        distance_html = _distance_block(row, language)
        if distance_html:
            html += f"{_section(_t('Préparation Distance', language))}"
            html += distance_html
        affinity_items = []
        for label, value in (
            ("Total", affinity_value),
            ("Base", affinity_base),
            ("Bonus G1", affinity_g1),
            (
                "Lien parents",
                affinity.get("parent_parent_base")
                if isinstance(affinity, dict)
                else None,
            ),
        ):
            if value is not None:
                affinity_items.append((_t(label, language), _number(value, 1)))
        if affinity_items:
            html += f"{_section(_t('Affinité moderne', language))}"
            html += _facts_table(affinity_items)
        if kind == "pair":
            g1_html = _g1_plan_block(
                row,
                language,
                left_name=_identity_name(row.get("parent_1")),
                right_name=_identity_name(row.get("parent_2")),
            )
            if g1_html:
                html += _section(_t("Planning G1 d’affinité", language))
                html += g1_html
    elif kind == "future":
        affinity_items = [
            (_t("Contribution du candidat", language), _number(row.get("affinity_raw"), 1)),
        ]
        if row.get("future_parent_base_affinity") is not None:
            affinity_items.append(
                (
                    _t("Base Ace × parent ciblé", language),
                    _number(row.get("future_parent_base_affinity"), 1),
                )
            )
        if row.get("future_branch_base_total") is not None:
            affinity_items.append(
                (
                    _t("Total de branche projeté", language),
                    _number(row.get("future_branch_base_total"), 1),
                )
            )
        affinity_items.append(
            (_t("G1 différentes", language), int(row.get("g1_count") or 0))
        )
        html += _facts_table(affinity_items)
    html += _spark_recap(row, kind, language)
    generation_html = _white_generation_block(row, language)
    if generation_html:
        html += _section(_t("Gains de génération des White Sparks", language))
        html += generation_html
    html += f"{_section(_t('Calcul du score global', language))}{_component_table(row, language)}"
    factor_html = _top_factors(row, language)
    if factor_html:
        html += f"{_section(_t('Facteurs principaux', language))}{factor_html}"
    return html


def online_detail_html(
    row: dict[str, Any] | None,
    mode: str,
    language: str,
    profile: dict[str, Any] | None = None,
) -> str:
    if not row:
        return result_detail_html(None, "pair", language)
    local_key = "fixed_parent" if mode == "parent" else "fixed_grandparent"
    local = row.get(local_key) or {}
    remote = row.get("candidate") or {}
    online = remote.get("online") or {}
    title = f"{_identity_name(local)}  ×  {_identity_name(remote)}"
    friend = str(online.get("friend_code") or "—")
    trainer = str(online.get("trainer_name") or "—")
    visual_mode = "online_parent" if mode == "parent" else "online_grandparent"
    metric_kind = "pair" if mode == "parent" else "grandparent_pair"
    # Les identifiants restent sous le titre : la clé uma.moe du candidat
    # distant est trop longue pour tenir sur la ligne de titre.
    subtitle = " · ".join(
        part
        for part in (
            trainer,
            f"Friend ID {friend}" if friend != "—" else "",
            "  ×  ".join(
                value
                for value in (_identity_meta(local), _identity_meta(remote))
                if value
            ),
        )
        if part
    )
    html = f"""
    {_detail_styles()}
    <div class='eyebrow'>{escape(_t('Paire locale × distante', language))}</div>
    <h2>{escape(title)}</h2>
    <div class='muted'>{escape(subtitle)}</div>
    {_metric_strip(row, metric_kind, language)}
    """
    if mode == "parent":
        affinity = row.get("affinity") or {}
        aptitude_html = _aptitude_block(row, language, profile)
        if aptitude_html:
            html += f"{_section(_t('Aptitudes — héritage visé', language))}"
            html += aptitude_html
        distance_html = _distance_block(row, language)
        if distance_html:
            html += f"{_section(_t('Préparation Distance', language))}"
            html += distance_html
        affinity_items = [
            (_t(label, language), _number(value, 1))
            for label, value in (
                ("Total", affinity.get("total")),
                ("Base", affinity.get("base")),
                ("Bonus G1", affinity.get("g1_bonus")),
                ("Lien parents", affinity.get("parent_parent_base")),
            )
            if value is not None
        ]
        if affinity_items:
            html += _section(_t("Affinité moderne", language))
            html += _facts_table(affinity_items)
        g1_html = _g1_plan_block(
            row,
            language,
            left_name=_identity_name(local),
            right_name=_identity_name(remote),
        )
        if g1_html:
            html += _section(_t("Planning G1 d’affinité", language))
            html += g1_html
    else:
        affinity = row.get("final_parent_affinity") or row.get("final_branch_affinity") or {}
        html += _section(_t("Potentiel du parent final", language))
        html += _facts_table(
            [
                (_t(label, language), _number(value, 1))
                for label, value in (
                    ("Base finale", affinity.get("base")),
                    ("Bonus G1 pondéré", affinity.get("planned_g1_bonus")),
                    ("Potentiel final", affinity.get("potential_total", affinity.get("total"))),
                    ("G1 communes", affinity.get("common_g1_count")),
                )
            ]
        )
        g1_html = _g1_plan_block(
            row,
            language,
            left_name=_identity_name(local),
            right_name=_identity_name(remote),
        )
        if g1_html:
            html += _section(_t("Planning G1 d’affinité", language))
            html += g1_html
        aptitude_html = _aptitude_block(row, language, profile)
        if aptitude_html:
            html += _section(_t("Projection de la paire finale", language))
            context_items = []
            if row.get("projected_future_parent"):
                context_items.append(
                    (
                        _t("Parent projeté", language),
                        _identity_name(row.get("projected_future_parent")),
                    )
                )
            if row.get("opposing_parent"):
                context_items.append(
                    (
                        _t("Parent opposé", language),
                        _identity_name(row.get("opposing_parent")),
                    )
                )
            if context_items:
                html += _facts_table(context_items)
            html += aptitude_html
            distance_html = _distance_block(row, language)
            if distance_html:
                html += distance_html
        production_html = _production_affinity_block(row, language)
        if production_html:
            html += _section(_t("Affinité de la run de production", language))
            html += production_html
    html += _spark_recap(row, visual_mode, language)
    generation_html = _white_generation_block(row, language)
    if generation_html:
        html += _section(_t("Gains de génération des White Sparks", language))
        html += generation_html
    html += f"{_section(_t('Calcul du score global', language))}{_component_table(row, language)}"
    factors = _top_factors(row, language)
    if factors:
        html += f"{_section(_t('Facteurs principaux', language))}{factors}"
    return html


def transfer_detail_html(row: dict[str, Any] | None, language: str) -> str:
    if not row:
        return result_detail_html(None, "pair", language)
    replacement = row.get("dominated_by") or {}
    statuses = {
        "safe_transfer": "Équivalent dans le modèle",
        "recommended_transfer": "Redondant dans le modèle",
        "review": "À examiner",
        "keep": "Conserver",
        "protected": "Protégé",
    }
    reasons = {
        "strictly_dominated_same_card": "Un remplaçant strict de la même carte et de la même unique couvre toutes les niches viables.",
        "redundant_in_collection_portfolio": "La copie est redondante dans le portefeuille conservé ; sa couverture peut être répartie sur plusieurs vétérans.",
        "required_by_collection_portfolio": "Cette copie est nécessaire pour préserver une niche compétitive ou un patrimoine stratégique du costume.",
        "locked_in_game": "Ce vétéran est verrouillé en jeu et ne peut jamais être recommandé au transfert.",
        "memo_present": "Ce vétéran porte un mémo et reste protégé.",
        "portfolio_coverage_incomplete": "La couverture du portefeuille est incomplète : vérification manuelle nécessaire.",
        "no_meaningful_role_detected": "Aucun rôle compétitif n’atteint les seuils, sans remplaçant strict confirmé.",
        "strong_grandparent_value": "Forte valeur comme futur grand-parent.",
        "strong_parent_value": "Forte valeur comme parent.",
        "strong_value_in_multiple_roles": "Valeur compétitive dans plusieurs rôles ou profils.",
        "narrow_or_single_context_niche": "Niche plausible mais étroite : vérification manuelle recommandée.",
        "protected_repeated_white_spark": "Une white Spark utile et fortement répétée n’est pas suffisamment préservée par le remplaçant.",
        "protected_hard_to_obtain_spark": "Une Spark utile difficile à obtenir autrement n’est pas suffisamment préservée par le remplaçant.",
        "protected_direct_future_gp_spark": "Une Spark directe à forte valeur de futur grand-parent n’est pas suffisamment préservée par le remplaçant.",
        "protected_important_skill_set": "La qualité d’un package de Sparks important est dégradée par le remplaçant.",
        "protected_package_not_preserved_by_replacement": "Un package de Sparks important n’est pas préservé par le remplaçant.",
    }
    status = _t(statuses.get(str(row.get("status")), str(row.get("status") or "—")), language)
    title = _identity(row)
    reason = _t(reasons.get(str(row.get("reason_code")), str(row.get("reason_code") or "—")), language)

    def profiles(items: list[dict[str, Any]]) -> str:
        rows = []
        for profile in items[:6]:
            label = str(profile.get("profile") or profile.get("context_key") or "—")
            rows.append(
                f"<tr><td>{escape(label)}</td>"
                f"<td align='right'>{_number(profile.get('score'), 2)}</td>"
                f"<td align='right'>top {_number(profile.get('percentile'), 1)}%</td></tr>"
            )
        return "".join(rows) or f"<tr><td colspan='3'>{escape(_t('Aucun', language))}</td></tr>"

    def evidence_reading(evidence: dict[str, Any]) -> str:
        if evidence.get("elite") or evidence.get("repeated"):
            return _t("Compétitif", language)
        if int(evidence.get("competitive_context_count") or 0) > 0:
            return _t("Niche étroite", language)
        return _t("Aucun rôle compétitif", language)

    def evidence_row(role: str, evidence: dict[str, Any]) -> str:
        competitive = int(evidence.get("competitive_context_count") or 0)
        evaluated = int(evidence.get("evaluated_context_count") or 0)
        distinct = int(evidence.get("competitive_distinct_profile_count") or 0)
        distinct_evaluated = int(
            evidence.get("evaluated_distinct_profile_count") or 0
        )
        elite = int(evidence.get("elite_context_count") or 0)
        competitive_text = (
            f"{competitive} / {evaluated}" if evaluated else str(competitive)
        )
        distinct_text = (
            f"{distinct} / {distinct_evaluated}"
            if distinct_evaluated
            else str(distinct)
        )
        return (
            "<tr>"
            f"<td><b>{escape(role)}</b></td>"
            f"<td align='right'>{competitive_text}</td>"
            f"<td align='right'>{distinct_text}</td>"
            f"<td align='right'>{elite}</td>"
            f"<td>{escape(evidence_reading(evidence))}</td>"
            "</tr>"
        )

    spark_type_labels = {
        "blue_stat": "Bleue",
        "red_aptitude": "Rose",
        "white_skill": "White",
        "white_race": "Course",
        "race": "Course",
        "scenario": "Scénario",
        "unique": "Unique",
    }
    spark_type_order = {
        "blue_stat": 0,
        "red_aptitude": 1,
        "white_skill": 2,
        "white_race": 3,
        "race": 3,
        "scenario": 4,
        "unique": 5,
    }

    def snapshot(identity: dict[str, Any]) -> dict[tuple[str, str], int]:
        result: dict[tuple[str, str], int] = {}
        for factor in (identity.get("sparks") or {}).get("all") or []:
            if not isinstance(factor, dict):
                continue
            factor_type = str(factor.get("type") or "unknown")
            name = str(factor.get("name") or "").strip()
            if not name:
                continue
            key = (factor_type, name)
            result[key] = result.get(key, 0) + int(factor.get("stars") or 0)
        return result

    def spark_comparison(
        candidate: dict[str, Any],
        retained: list[dict[str, Any]],
    ) -> str:
        retained_snapshots_available = all(
            isinstance(item.get("sparks"), dict)
            and isinstance((item.get("sparks") or {}).get("all"), list)
            for item in retained
        )
        if retained and not retained_snapshots_available:
            return (
                f"<p class='muted'>{escape(_t('Les Sparks des copies conservées sont absentes de cet ancien rapport ; relance l’analyse pour obtenir la comparaison.', language))}</p>"
            )
        candidate_sparks = snapshot(candidate)
        retained_sparks = [snapshot(item) for item in retained]
        retained_labels = canonical_veteran_labels(
            retained,
            rank_label=_t("Rang", language).casefold(),
            blue_label=_t("Bleues", language).casefold(),
        )
        keys = set(candidate_sparks)
        for item in retained_sparks:
            keys.update(item)
        ordered = sorted(
            keys,
            key=lambda key: (
                spark_type_order.get(key[0], 99),
                key[1].casefold(),
            ),
        )
        if not ordered:
            return f"<p class='muted'>{escape(_t('Aucune Spark disponible dans le rapport.', language))}</p>"
        rows = []
        for factor_type, name in ordered:
            candidate_stars = candidate_sparks.get((factor_type, name))
            retained_values = [
                (label, values.get((factor_type, name)))
                for label, values in zip(retained_labels, retained_sparks)
                if values.get((factor_type, name)) is not None
            ]
            retained_text = (
                f"{int(retained_values[0][1] or 0)}★"
                if len(retained) == 1 and retained_values
                else "<br>".join(
                    f"{int(stars or 0)}★ · {escape(label)}"
                    for label, stars in retained_values
                )
                if retained_values
                else escape(_t("Absente", language))
            )
            candidate_text = (
                f"{int(candidate_stars)}★"
                if candidate_stars is not None
                else escape(_t("Absente", language))
            )
            type_label = _t(
                spark_type_labels.get(factor_type, factor_type or "Spark"),
                language,
            )
            rows.append(
                "<tr>"
                f"<td><span class='muted'>{escape(type_label)}</span><br>"
                f"<b>{escape(name)}</b></td>"
                f"<td align='right'>{candidate_text}</td>"
                f"<td>{retained_text}</td>"
                "</tr>"
            )
        retained_heading = (
            _t("Remplaçant", language)
            if len(retained) == 1
            else _t("Couverture conservée", language)
        )
        return (
            "<table><tr>"
            f"<td><b>{escape(_t('Spark', language))}</b></td>"
            f"<td><b>{escape(_t('Vétéran', language))}</b></td>"
            f"<td><b>{escape(retained_heading)}</b></td>"
            "</tr>"
            + "".join(rows)
            + "</table>"
        )

    def stats_summary(identity: dict[str, Any]) -> str:
        stats = identity.get("stats") or {}
        fields = (
            ("Vitesse", "speed"),
            ("Endurance", "stamina"),
            ("Puissance", "power"),
            ("Cran", "guts"),
            ("Intelligence", "wiz"),
        )
        values = [
            f"{_t(label, language)} {int(stats.get(key) or 0)}"
            for label, key in fields
            if stats.get(key) is not None
        ]
        return " · ".join(values) or "—"

    def lineage_summary(identity: dict[str, Any]) -> str:
        grandparents = [
            str(identity.get(key) or "").strip()
            for key in ("grandparent_1", "grandparent_2")
        ]
        return " × ".join(value for value in grandparents if value) or "—"

    def signed_number(value: object, digits: int = 3) -> str:
        try:
            return f"{float(value):+.{digits}f}"
        except (TypeError, ValueError):
            return "—"

    def context_delta_label(item: dict[str, Any] | None) -> str:
        if not item:
            return "—"
        label = str(item.get("profile") or item.get("context_key") or "—")
        role = _t(
            "Parent" if item.get("role") == "parent" else "Futur grand-parent",
            language,
        )
        return f"{role} · {label} · {signed_number(item.get('delta'))}"

    def context_delta_table(evidence: dict[str, Any]) -> str:
        rows = []
        for item in evidence.get("context_deltas") or []:
            role = _t(
                "Parent"
                if item.get("role") == "parent"
                else "Futur grand-parent",
                language,
            )
            retained_by = list(item.get("retained_by") or [])
            retained_label = "<br>".join(
                escape(label)
                for label in canonical_veteran_labels(
                    retained_by,
                    rank_label=_t("Rang", language).casefold(),
                    blue_label=_t("Bleues", language).casefold(),
                )
            )
            replacement_score = _number(item.get("replacement_score"), 3)
            if retained_label:
                replacement_score += f"<br><span class='muted'>{retained_label}</span>"
            rows.append(
                "<tr>"
                f"<td>{escape(role)}</td>"
                f"<td>{escape(str(item.get('profile') or item.get('context_key') or '—'))}</td>"
                f"<td align='right'>{_number(item.get('candidate_score'), 3)}</td>"
                f"<td align='right'>{replacement_score}</td>"
                f"<td align='right'><b>{signed_number(item.get('delta'))}</b></td>"
                "</tr>"
            )
        if not rows:
            return ""
        return (
            f"<h3>{escape(_t('Écarts par contexte', language))}</h3>"
            f"<p class='muted'>{escape(_t('Chaque score est comparé pour le même Ace ; le tableau retient le cas le moins favorable de chaque contexte. Un delta positif favorise la couverture conservée.' if any(item.get('ace_card_id') for item in evidence.get('context_deltas') or []) else 'Chaque score est la meilleure enveloppe obtenue parmi les Aces viables du profil ; un delta positif favorise la couverture conservée.', language))}</p>"
            "<table><tr>"
            f"<td><b>{escape(_t('Rôle', language))}</b></td>"
            f"<td><b>{escape(_t('Contexte', language))}</b></td>"
            f"<td><b>{escape(_t('Candidat', language))}</b></td>"
            f"<td><b>{escape(_t('Couverture', language))}</b></td>"
            f"<td><b>{escape(_t('Écart', language))}</b></td>"
            "</tr>"
            + "".join(rows)
            + "</table>"
        )

    html = f"""
    <style>
      body {{ color:{PANEL['text']}; font-size:{FONT_SIZE['body']}; line-height:1.45; }}
      h2 {{ margin:0 0 4px; font-size:{FONT_SIZE['heading']}; font-weight:800; }}
      h3 {{ color:#dce8f6; margin:17px 0 7px; font-size:{FONT_SIZE['section']}; font-weight:750; }}
      .eyebrow {{ color:{PANEL['accent']}; font-weight:750; font-size:{FONT_SIZE['micro']}; }}
      .muted {{ color:{PANEL['muted']}; font-size:{FONT_SIZE['caption']}; }}
      .replacement {{ background:{PANEL['surface']}; border-left:3px solid {PANEL['accent']}; padding:9px 11px; margin-top:8px; }}
      .protection {{ background:{PANEL['surface_alt']}; border-left:3px solid {PANEL['gold']}; padding:9px 11px; margin-top:8px; }}
      table {{ width:100%; border-collapse:collapse; }}
      td {{ color:{PANEL['text_soft']}; padding:6px 1px; border-bottom:1px solid {PANEL['border_soft']}; }}
      .facts-table th {{ width:52%; color:{PANEL['muted']}; text-align:left; font-size:{FONT_SIZE['caption']}; font-weight:600; padding:6px 2px 6px 1px; border-bottom:1px solid {PANEL['border_soft']}; }}
      .facts-table td {{ color:{PANEL['text']}; font-size:{FONT_SIZE['body']}; padding:6px 1px 6px 2px; border-bottom:1px solid {PANEL['border_soft']}; }}
      .facts-table .facts-last {{ border-bottom:0; }}
    </style>
    <div class='eyebrow'>{escape(status)}</div>
    <h2>{escape(title)}</h2>
    <div class='muted'>{escape(reason)}</div>
    {_facts_table([
        (_t('Score en jeu', language), format_rank_score(row.get('rank_score'))),
        (_t('Verrouillé en jeu', language), _t('Oui', language) if row.get('is_locked') else _t('Non', language)),
        (_t('Mémo', language), str(row.get('memo') or '—')),
        (_t('Copies comparables', language), int(row.get('same_card_copy_count') or 0)),
        (
            _t('Indice du modèle — parent', language),
            f"{_number(row.get('best_parent_score'), 2)} · top {_number(row.get('best_parent_percentile'), 1)}%",
        ),
        (
            _t('Indice du modèle — GP', language),
            f"{_number(row.get('best_grandparent_score'), 2)} · top {_number(row.get('best_grandparent_percentile'), 1)}%",
        ),
    ])}
    """
    parent_evidence = row.get("parent_evidence") or {}
    if row.get("manual_protection_reasons") and row.get("analysis_status"):
        analytical = _t(statuses.get(str(row["analysis_status"]), str(row["analysis_status"])), language)
        html += (
            f"<div class='protection'><b>{escape(_t('Protégé — diagnostic seulement', language))}</b><br>"
            f"{escape(_t('Valeur calculée', language))} : {escape(analytical)}</div>"
        )
    grandparent_evidence = row.get("grandparent_evidence") or {}
    html += (
        f"<h3>{escape(_t('Preuves du verdict', language))}</h3>"
        "<table><tr>"
        f"<td><b>{escape(_t('Rôle', language))}</b></td>"
        f"<td><b>{escape(_t('Contextes compétitifs', language))}</b></td>"
        f"<td><b>{escape(_t('Profils distincts', language))}</b></td>"
        f"<td><b>{escape(_t('Contextes élite', language))}</b></td>"
        f"<td><b>{escape(_t('Lecture', language))}</b></td>"
        "</tr>"
        + evidence_row(_t("Parent", language), parent_evidence)
        + evidence_row(_t("Futur grand-parent", language), grandparent_evidence)
        + "</table>"
    )
    if replacement:
        html += (
            f"<h3>{escape(_t('Remplaçant retenu', language))}</h3><div class='replacement'>"
            f"<b>{escape(_identity(replacement))}</b><br>"
            + _facts_table(
                [
                    (
                        _t("Avance moyenne", language),
                        signed_number(replacement.get("mean_score_lead")),
                    ),
                    (
                        _t("Pire écart observé", language),
                        signed_number(replacement.get("worst_context_delta")),
                    ),
                    (
                        _t("Meilleur écart observé", language),
                        signed_number(replacement.get("best_context_delta")),
                    ),
                    (
                        _t("Contexte le plus serré", language),
                        context_delta_label(replacement.get("worst_context")),
                    ),
                    (
                        _t("Contexte le plus favorable", language),
                        context_delta_label(replacement.get("best_context")),
                    ),
                    (
                        _t("Comparaisons parent viables", language),
                        int(replacement.get("viable_parent_comparisons") or 0),
                    ),
                    (
                        _t("Comparaisons grand-parent viables", language),
                        int(
                            replacement.get("viable_grandparent_comparisons")
                            or 0
                        ),
                    ),
                    (_t("Rang en jeu", language), replacement.get("rank") or "—"),
                    (_t("Stats", language), stats_summary(replacement)),
                    (_t("Lignée", language), lineage_summary(replacement)),
                ]
            )
            + "</div>"
            + context_delta_table(replacement)
        )
    coverage = list(row.get("covered_by_portfolio") or [])
    if coverage and not replacement:
        coverage_labels = canonical_veteran_labels(
            coverage,
            rank_label=_t("Rang", language).casefold(),
            blue_label=_t("Bleues", language).casefold(),
        )
        html += (
            f"<h3>{escape(_t('Couverture collective', language))}</h3>"
            "<div class='replacement'>"
            + "<br>".join(
                f"<b>{escape(label)}</b>"
                for label in coverage_labels
            )
            + "</div>"
        )
        portfolio_comparison = row.get("portfolio_comparison") or {}
        if portfolio_comparison.get("context_deltas"):
            html += _facts_table(
                [
                    (
                        _t("Avance moyenne", language),
                        signed_number(
                            portfolio_comparison.get("mean_score_lead")
                        ),
                    ),
                    (
                        _t("Contexte le plus serré", language),
                        context_delta_label(
                            portfolio_comparison.get("worst_context")
                        ),
                    ),
                    (
                        _t("Contexte le plus favorable", language),
                        context_delta_label(
                            portfolio_comparison.get("best_context")
                        ),
                    ),
                ]
            )
            html += context_delta_table(portfolio_comparison)
    required_for = list(row.get("portfolio_required_for") or [])
    if required_for:
        html += (
            f"<h3>{escape(_t('Pourquoi cette copie est conservée', language))}</h3>"
            "<table>"
            + "".join(
                f"<tr><td>{escape(str(item.get('label') or item.get('key') or '—'))}</td></tr>"
                for item in required_for
            )
            + "</table>"
        )
    retained = [replacement] if replacement else coverage
    if retained:
        html += (
            f"<h3>{escape(_t('Comparaison complète des Sparks', language))}</h3>"
            f"<p class='muted'>{escape(_t('Toutes les Sparks du vétéran sont comparées au remplaçant ou aux copies conservées ; ce tableau reste visible même quand le transfert est recommandé.', language))}</p>"
            + spark_comparison(row, retained)
        )
    protection = row.get("spark_protection") or {}

    def heritage_metrics(item: dict[str, Any]) -> str:
        if not item.get("present"):
            return _t("Absente", language)
        values = [
            _t("{count} porteur(s)", language).replace(
                "{count}", str(int(item.get("carrier_count") or 0))
            ),
            f"{int(item.get('total_stars') or 0)}★",
            f"P={_percent(item.get('neutral_probability'), 1)}",
        ]
        if item.get("direct"):
            values.append(
                _t("directe {stars}★", language).replace(
                    "{stars}", str(int(item.get("direct_total_stars") or 0))
                )
            )
        generation_count = int(
            item.get("white_generation_carrier_count") or 0
        )
        if generation_count:
            values.append(
                _t("génération ×{count}", language).replace(
                    "{count}", str(generation_count)
                )
            )
        support_count = item.get("direct_support_hint_card_count")
        if isinstance(support_count, int) and not isinstance(support_count, bool):
            values.append(
                _t("{count} support(s) avec hint direct", language).replace(
                    "{count}", str(support_count)
                )
            )
        return " · ".join(values)

    protected_skill_rows = []
    protected_comparisons = list(protection.get("protected_skills") or [])
    if not protected_comparisons:
        protected_comparisons = [
            deficit
            for deficit in protection.get("deficits") or []
            if deficit.get("kind") == "skill"
        ]
    for comparison in protected_comparisons:
        preserved = bool(comparison.get("preserved_by_replacement"))
        protected_skill_rows.append(
            "<tr>"
            f"<td><b>{escape(str(comparison.get('name') or comparison.get('catalog_key') or '—'))}</b></td>"
            f"<td>{escape(heritage_metrics(comparison.get('candidate') or {}))}</td>"
            f"<td>{escape(heritage_metrics(comparison.get('replacement') or {}))}</td>"
            f"<td>{escape(_t('Préservée' if preserved else 'Non préservée', language))}</td>"
            "</tr>"
        )
    if protected_skill_rows:
        html += (
            f"<h3>{escape(_t('Patrimoine protégé comparé', language))}</h3>"
            f"<p class='muted'>{escape(_t('Les protections stratégiques restent détaillées même lorsqu’elles sont correctement couvertes.', language))}</p>"
            "<table><tr>"
            f"<td><b>{escape(_t('Spark concernée', language))}</b></td>"
            f"<td><b>{escape(_t('Vétéran', language))}</b></td>"
            f"<td><b>{escape(_t('Remplaçant', language))}</b></td>"
            f"<td><b>{escape(_t('État', language))}</b></td>"
            "</tr>"
            + "".join(protected_skill_rows)
            + "</table>"
        )

    if protection.get("applied"):
        reason_labels = {
            "protected_repeated_white_spark": "White répétée",
            "protected_hard_to_obtain_spark": "Acquisition difficile",
            "protected_direct_future_gp_spark": "Spark directe de futur GP",
            "protected_important_skill_set": "Package dégradé",
            "protected_package_not_preserved_by_replacement": "Package non préservé",
        }

        package_rows = []
        package_labels = {
            "general_backliner": _t("Noyau polyvalent des backliners", language),
            "front_groundwork": _t("Préparation Groundwork Front", language),
            "pace_acceleration": _t("Accélération Pace Chaser", language),
            "closer_acceleration": _t("Accélération End Closer", language),
        }
        for deficit in protection.get("deficits") or []:
            if deficit.get("kind") == "skill":
                continue
            missing = [
                str(key).replace("_", " ").title()
                for key in deficit.get("missing_skills") or []
            ]
            degraded = [
                str(key).replace("_", " ").title()
                for key in deficit.get("degraded_skills") or []
            ]
            details = []
            if missing:
                details.append(
                    _t("Manquantes : {skills}", language).replace(
                        "{skills}", ", ".join(missing)
                    )
                )
            if degraded:
                details.append(
                    _t("Couverture réduite : {skills}", language).replace(
                        "{skills}", ", ".join(degraded)
                    )
                )
            package_rows.append(
                "<tr>"
                f"<td><b>{escape(package_labels.get(str(deficit.get('key') or ''), str(deficit.get('label') or deficit.get('key') or '—')))}</b></td>"
                f"<td>{int(deficit.get('candidate_distinct_count') or 0)} · "
                f"{int(deficit.get('candidate_total_stars') or 0)}★</td>"
                f"<td>{int(deficit.get('replacement_distinct_count') or 0)} · "
                f"{int(deficit.get('replacement_total_stars') or 0)}★"
                f"<br><span class='muted'>{escape(' · '.join(details))}</span></td>"
                "</tr>"
            )

        labels = [
            _t(reason_labels.get(str(code), str(code)), language)
            for code in protection.get("reason_codes") or []
        ]
        html += (
            f"<h3>{escape(_t('Protection du patrimoine Spark', language))}</h3>"
            "<div class='protection'>"
            f"<b>{escape(_t('Plancher de verdict', language))}: "
            f"{escape(_t(statuses.get(str(protection.get('verdict_floor')), str(protection.get('verdict_floor') or '—')), language))}</b>"
            f"<br><span class='muted'>{escape(' · '.join(labels))}</span>"
            "</div>"
        )
        if package_rows:
            html += (
                f"<h3>{escape(_t('Packages non préservés', language))}</h3>"
                "<table><tr>"
                f"<td><b>{escape(_t('Package concerné', language))}</b></td>"
                f"<td><b>{escape(_t('Vétéran', language))}</b></td>"
                f"<td><b>{escape(_t('Remplaçant', language))}</b></td>"
                "</tr>"
                + "".join(package_rows)
                + "</table>"
            )
    html += f"<h3>{escape(_t('Meilleurs profils parent', language))}</h3><table>{profiles(list(row.get('top_parent_profiles') or []))}</table>"
    html += f"<h3>{escape(_t('Meilleurs profils grand-parent', language))}</h3><table>{profiles(list(row.get('top_grandparent_profiles') or []))}</table>"
    html += f"<p class='muted'>{escape(_t('L’outil ne modifie pas l’export source et ne supprime rien en jeu.', language))}</p>"
    return html

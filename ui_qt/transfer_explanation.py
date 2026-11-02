"""Concrete gains and concessions, reconstructed from a frozen report.

This explains an existing comparison. It cannot change a portfolio decision.
Stars, skill utilities and index points are deliberately kept in separate units.
"""
from html import escape
from math import isfinite
from math import isfinite

from uma_legacy_linker.transfer_comparison import comparison_evaluation, factor_inventory, white_inventory
from uma_legacy_linker.skill_catalog import slugify
from uma_legacy_linker.parent_optimizer import _scenario_stat_targets
from ui_qt.theme import COLORS


COMPONENT_LABELS = {
    'blue': 'Bleues', 'distance_s': 'Distance S', 'surface_aptitude': 'Aptitude surface',
    'pink_other': 'Autres roses', 'pink': 'Roses', 'white_skill': 'Whites',
    'white_generation': 'Génération White', 'race_scenario': 'Course / scénario',
    'unique': 'Unique', 'g1_potential': 'Potentiel G1', 'affinity': 'Affinité',
}


def spark_duel(candidate, target, model, key, ace_index, role, evaluations=None, limit=6):
    """Build aligned, role-relevant spark rows after verifying both frozen scores."""
    try:
        left, right = evaluations or (
            comparison_evaluation(candidate, model, key, ace_index, role),
            comparison_evaluation(target, model, key, ace_index, role),
        )
        for record, value in ((candidate, left), (target, right)):
            saved = record.get('comparison_profiles', {}).get(role, {}).get(key, [])
            score = value.get('score')
            if (ace_index >= len(saved) or score is None or saved[ace_index] is None
                    or not all(isfinite(float(v)) for v in (score, saved[ace_index]))
                    or abs(float(saved[ace_index]) - float(score)) > 1e-5):
                return {'available': False, 'factors': [], 'folded': 0}
        context = model['contexts'][key]
        inventories = [factor_inventory(record, role) for record in (candidate, target)]
        skill_rows = [white_inventory(item) for item in (left, right)]
        axes = {'Turf': 'surface', 'Dirt': 'surface', 'Sprint': 'distance', 'Mile': 'distance',
                'Medium': 'distance', 'Long': 'distance', 'Front Runner': 'style',
                'Pace Chaser': 'style', 'Late Surger': 'style', 'End Closer': 'style'}
        items = []
        for factor_key in set(inventories[0]) | set(inventories[1]):
            kind = factor_key[0]
            l, r = (inventory.get(factor_key, {}) for inventory in inventories)
            name = str(l.get('name') or r.get('name') or factor_key[1])
            inactive_reason = ""
            if kind == 'blue_stat':
                relevance = float(left['weights'].get('blue', 0)) * float(left['details']['blue'].get('stat_weights', {}).get(name, 1))
            elif kind == 'unique':
                relevance = float(left['weights'].get('unique', 0))
            elif kind == 'red_aptitude':
                dimension = axes.get(name)
                if dimension is None:
                    relevance = 0.0
                    inactive_reason = "Aptitude non reconnue par le modèle."
                elif name.casefold() != str(context.get(dimension, '')).replace('_', ' ').title().casefold():
                    relevance = 0.0
                    inactive_reason = "Aptitude hors du profil de course sélectionné."
                elif role == 'parent':
                    component = {
                        'distance': 'distance_s',
                        'surface': 'surface_aptitude',
                        'style': 'pink_other',
                    }[dimension]
                    relevance = float(left['weights'].get(component, 0))
                    if relevance <= 0:
                        inactive_reason = "Poids nul pour cette composante dans ce profil."
                else:
                    pink = left['details'].get('pink', {})
                    dimension_detail = (pink.get('dimensions') or {}).get(dimension) or {}
                    relevance = (
                        float(left['weights'].get('pink', 0))
                        * float(dimension_detail.get('dimension_weight', 0))
                    )
                    if relevance <= 0:
                        inactive_reason = "Poids nul pour cette composante dans ce profil."
            elif kind == 'white_skill':
                skill_key = next((skill for skill, item in (skill_rows[0] | skill_rows[1]).items()
                                  if slugify(name) == skill or slugify(str(item.get('name') or '')) == slugify(name)), '')
                profile_weight = float(context.get('skill_weights', {}).get(skill_key, 0))
                relevance = profile_weight * float(left['weights'].get('white_skill', 0))
                if not skill_key or relevance <= 0:
                    continue
                name = str((skill_rows[0].get(skill_key) or skill_rows[1].get(skill_key) or {}).get('name') or name)
            elif kind == 'white_race':
                grants = (model.get('race_skills') or {}).get(name, [])
                profile_weight = max((float(context.get('skill_weights', {}).get(skill, 0))
                                      for skill in grants), default=0.0)
                white_relevance = profile_weight * float(left['weights'].get('white_skill', 0))
                race_relevance = float(left['weights'].get('race_scenario', 0)) if role == 'parent' else 0.0
                relevance = max(white_relevance, race_relevance)
                if relevance <= 0:
                    continue
            elif kind == 'scenario':
                targets, _source = _scenario_stat_targets(l or r)
                stat_weights = left['details']['blue'].get('stat_weights', {})
                relevance = float(left['weights'].get('blue', 0)) * sum(
                    max(0.0, float(stat_weights.get(stat, 0))) for stat in targets
                )
            else:
                continue
            if relevance <= 0:
                if kind == 'blue_stat':
                    inactive_reason = "Poids nul pour cette composante dans ce profil."
                    items.append({
                        'key': factor_key, 'type': kind, 'role': role, 'name': name,
                        'left_stars': int(l.get('stars') or 0),
                        'right_stars': int(r.get('stars') or 0),
                        'left_carriers': list(l.get('carriers') or []),
                        'right_carriers': list(r.get('carriers') or []),
                        'priority': 0.0, 'is_inactive': True,
                        'inactive_reason': inactive_reason,
                    })
                elif kind == 'red_aptitude' and inactive_reason:
                    items.append({
                        'key': factor_key, 'type': kind, 'role': role, 'name': name,
                        'left_stars': int(l.get('stars') or 0),
                        'right_stars': int(r.get('stars') or 0),
                        'left_carriers': list(l.get('carriers') or []),
                        'right_carriers': list(r.get('carriers') or []),
                        'priority': 0.0, 'is_inactive': True,
                        'inactive_reason': inactive_reason,
                    })
                continue
            left_carriers = list(l.get('carriers') or [])
            right_carriers = list(r.get('carriers') or [])
            items.append({
                'key': factor_key, 'type': kind, 'role': role, 'name': name,
                'left_stars': int(l.get('stars') or 0), 'right_stars': int(r.get('stars') or 0),
                'left_carriers': left_carriers if role == 'parent' else [('self', int(l.get('direct_stars') or 0))],
                'right_carriers': right_carriers if role == 'parent' else [('self', int(r.get('direct_stars') or 0))],
                'priority': relevance * max(1, int(l.get('stars') or 0), int(r.get('stars') or 0)),
            })
        items.sort(key=lambda item: (
            bool(item.get('is_inactive')), -item['priority'],
            item['name'].casefold(), str(item['key']),
        ))
        # Keep every stat total visible, even when a stat has no weight for
        # this distance; mark zero-weight stats inactive instead of folding
        # their total into a generic "other sparks" count.
        stats = [item for item in items if item.get('type') == 'blue_stat']
        active = [item for item in items
                  if item.get('type') != 'blue_stat' and not item.get('is_inactive')]
        inactive = [item for item in items
                    if item.get('type') != 'blue_stat' and item.get('is_inactive')]
        remaining = max(0, limit - len(stats))
        return {'available': True, 'factors': stats + active[:remaining] + inactive,
                'folded': max(0, len(active) - remaining),
                'all_factors': items}
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return {'available': False, 'factors': [], 'folded': 0}


def comparison_explanation(candidate, target, model, key, ace_index, role, evaluations=None):
    """Return verified component deltas and relevant, concrete factor changes."""
    try:
        left, right = evaluations or (
            comparison_evaluation(candidate, model, key, ace_index, role),
            comparison_evaluation(target, model, key, ace_index, role),
        )
        for record, value in ((candidate, left), (target, right)):
            saved = record.get('comparison_profiles', {}).get(role, {}).get(key, [])
            score = value['score']
            if ace_index >= len(saved) or score is None or saved[ace_index] is None:
                return {'available': False}
            if not all(isfinite(float(v)) for v in (score, saved[ace_index])) or abs(float(saved[ace_index]) - score) > 1e-5:
                return {'available': False}
        context = model['contexts'][key]
        components = [dict(key=component, delta=right['contributions'].get(component, 0)
                           - left['contributions'].get(component, 0)) for component in left['weights']]
        inventories = [factor_inventory(record, role) for record in (candidate, target)]
        facts = []
        # Whites are ranked by contextual utility, not by star count alone.
        whites = [white_inventory(value) for value in (left, right)]
        white_points = max(left['weights'].get('white_skill', 0), 0)
        if white_points:
            for skill in set(whites[0]) | set(whites[1]):
                l, r = (inventory.get(skill, {}) for inventory in whites)
                change = float(r.get('contribution', 0)) - float(l.get('contribution', 0))
                if abs(change) < 1e-6 or float(context.get('skill_weights', {}).get(skill, 0)) <= 0:
                    continue
                facts.append(dict(kind='white', name=model.get('skill_labels', {}).get(skill)
                                  or l.get('name') or r.get('name') or skill,
                                  delta=change, priority=abs(change) * white_points,
                                  left=l.get('probability_at_least_once'), right=r.get('probability_at_least_once'),
                                  left_count=l.get('carrier_count', 0), right_count=r.get('carrier_count', 0),
                                  source_stars=[sum(int(f.get('stars') or 0) for f in value.get('details', {}).get('white', {}).get('top_factors', [])
                                                    if f.get('catalog_key') == skill) for value in (left, right)]))
        for factor in set(inventories[0]) | set(inventories[1]):
            kind = factor[0]
            if kind not in {'blue_stat', 'red_aptitude', 'unique'}:
                continue
            l, r = (inventory.get(factor, {}) for inventory in inventories)
            delta = int(r.get('stars', 0)) - int(l.get('stars', 0))
            if not delta:
                continue
            name = str(l.get('name') or r.get('name') or factor[1])
            if kind == 'blue_stat':
                importance = float(left['details']['blue'].get('stat_weights', {}).get(name, 1))
                weight = float(left['weights'].get('blue', 0))
            elif kind == 'unique':
                importance, weight = 1, float(left['weights'].get('unique', 0))
            else:
                # Show only profile aptitudes in the short explanation. Full
                # inventories remain available in Factors and G1 / the lineage.
                wanted = {'turf': 'Turf', 'dirt': 'Dirt', 'sprint': 'Sprint', 'mile': 'Mile',
                          'medium': 'Medium', 'long': 'Long', 'front_runner': 'Front Runner',
                          'pace_chaser': 'Pace Chaser', 'late_surger': 'Late Surger', 'end_closer': 'End Closer'}
                matches = [dimension for dimension in ('surface', 'distance', 'style')
                           if wanted.get(context.get(dimension)) == name]
                if not matches:
                    continue
                dimension = matches[0]
                importance = {'distance': 1, 'surface': .6, 'style': .4}[dimension]
                weight = float(left['weights'].get('pink', 0)) or sum(
                    float(left['weights'].get(k, 0)) for k in ('distance_s', 'surface_aptitude', 'pink_other'))
            if weight <= 0:
                continue
            facts.append(dict(kind=kind, name=name, delta=delta,
                              priority=abs(delta) * importance * weight,
                              left=int(l.get('stars', 0)), right=int(r.get('stars', 0))))
        if role == 'grandparent' and float(left['weights'].get('g1_potential', 0)) > 0:
            counts = [len(set((r.get('comparison_veteran') or {}).get('g1_wins', {}).get('names', [])))
                      for r in (candidate, target)]
            if counts[0] != counts[1]:
                facts.append(dict(kind='g1', name='G1', delta=counts[1]-counts[0],
                                  priority=abs(counts[1]-counts[0])*left['weights']['g1_potential'],
                                  left=counts[0], right=counts[1]))
        facts.sort(key=lambda f: (-f['priority'], f['name']))
        return dict(available=True, delta=right['score']-left['score'], role=role,
                    includes_history=role == 'grandparent' and float(left['weights'].get('white_generation', 0)) > 0,
                    components=sorted(components, key=lambda c: -abs(c['delta'])),
                    gains=[f for f in facts if f['delta'] > 0], losses=[f for f in facts if f['delta'] < 0])
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        # Missing/malformed legacy data must never produce a made-up reason.
        return {'available': False}


def fact_text(fact, translate):
    t = translate
    name = t(fact['name']) if fact['kind'] == 'g1' else fact['name']
    if fact['kind'] == 'white':
        l, r = fact['left'], fact['right']
        if l is not None or r is not None:
            detail = f"{float(l or 0):.0%} → {float(r or 0):.0%}"
            unit = t('chance dans le modèle')
        else:
            detail = f"{fact['source_stars'][0]}★ → {fact['source_stars'][1]}★"
            unit = t('étoiles des sources propres')
    elif fact['kind'] == 'g1':
        detail, unit = f"{fact['left']} → {fact['right']}", t('G1 gagnées')
    else:
        detail = f"{fact['left']}★ → {fact['right']}★"
        unit = t('facteurs propres' if fact.get('role') == 'grandparent' else 'étoiles cumulées')
    return str(name) + ' · ' + detail + ' · ' + unit


def explanation_html(explanation, translate, compact=False):
    t = translate
    if not explanation.get('available'):
        return '<p>' + escape(t('Décomposition indisponible : les données enregistrées ne permettent pas de vérifier les motifs.')) + '</p>'
    html = '' if compact else '<p>' + escape(t('Lecture : copie étudiée → copie comparée.')) + '</p>'
    for title, key, color in (('Ce que la copie comparée apporte', 'gains', COLORS['accent']),
                              ('Ce qu’on perd avec ce remplacement', 'losses', COLORS['warning'])):
        facts = explanation[key]
        limit = 1 if compact else 4
        html += f'<p><b style="color:{color}">' + escape(t(title)) + '</b><br>'
        if facts:
            for fact in facts[:limit]:
                html += '• ' + escape(fact_text(dict(fact, role=explanation['role']), t)) + '<br>'
            if len(facts) > limit:
                html += escape(t('{count} autres différences dans les détails.').replace('{count}', str(len(facts)-limit)))
        else:
            html += escape(t('Aucune différence pertinente identifiée dans cette catégorie.'))
        html += '</p>'
    entries = [c for c in explanation['components'] if abs(c['delta']) > 1e-6]
    if entries:
        html += '<p><b>' + escape(t('Ce qui pèse dans l’indice')) + '</b><br>'
        html += ' · '.join(escape(t(COMPONENT_LABELS.get(c['key'], c['key'])) + f" {c['delta']:+.2f}")
                           for c in entries[:3]) + ' ' + escape(t('points du modèle')) + '</p>'
    if not compact:
        html += '<p>' + escape(t('Les facteurs expliquent les différences ; leurs étoiles ou probabilités ne s’additionnent pas aux points de l’indice.')) + '</p>'
        footnote = 'Dans ce rapport, la génération White historique contribue aussi à l’indice GP.' if explanation.get('includes_history') else 'Parent : la branche complète compte. Futur GP : seuls les facteurs propres comptent.'
        html += '<p>' + escape(t(footnote)) + '</p>'
    return html

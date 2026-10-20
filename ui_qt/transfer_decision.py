"""A short decision explanation grounded in saved, same-Ace comparisons."""
from html import escape
from math import isfinite

from uma_legacy_linker.i18n import profile_label
from ui_qt.theme import COLORS
from ui_qt.transfer_explanation import comparison_explanation, explanation_html
from uma_legacy_linker.veteran_identity import game_veteran_label, game_rank_label, format_rank_score


def preserved_reasons(record, model, language, translate):
    """Human labels for the recorded obligations unique to a retained copy."""
    t = translate
    reasons = []
    required = record.get('portfolio_required_for') or []
    priority = {'protected_skill': 0, 'blue_3star': 1, 'pink_3star': 2, 'identity': 3, 'performance': 4}
    for item in sorted(required, key=lambda a: priority.get(a.get('kind'), 5)):
        kind = item.get('kind')
        if kind == 'performance':
            context = (model or {}).get('contexts', {}).get(item.get('context_key'))
            if not context:
                continue
            role = t('Parent' if item.get('role') == 'parent' else 'Futur grand-parent')
            prefix = t('Permanent') if context.get('scope') == 'permanent' else str(context.get('label') or '').split(' · ')[0]
            profile = ' · '.join(profile_label(d, str(context[d]), language)
                                 for d in ('surface', 'distance', 'style') if context.get(d))
            reason = role + ' · ' + prefix + ' · ' + profile
        elif kind == 'protected_skill':
            reason = t('Skill stratégique protégé') + ' : ' + str(item.get('label') or '—')
        elif kind in {'blue_3star', 'pink_3star'}:
            reason = t('Facteur 3★ à préserver') + ' : ' + str(item.get('label') or '—')
        elif kind == 'identity':
            reason = t('Dernière copie conservée de ce costume')
        else:
            reason = str(item.get('label') or '—')
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def decision_examples(record, records, model):
    """Prioritise losses, then practical Aces, using saved retained witnesses.

    Verify each witness against the saved score vectors and a retained copy.
    Older reports lacking those data can still display their advanced details.
    """
    if not record.get('comparison_group'):
        return []
    by_id = {str(r.get('trained_chara_id')): r for r in records}
    source = record.get('dominated_by') or record.get('portfolio_comparison') or {}
    valid = []
    for witness in source.get('context_deltas') or []:
        role, key = witness.get('role'), witness.get('context_key')
        context = model.get('contexts', {}).get(key, {})
        aces = context.get('aces', [])
        index = next((i for i, ace in enumerate(aces)
                      if ace.get('card_id') == witness.get('ace_card_id')), None)
        if role not in {'parent', 'grandparent'} or index is None:
            continue
        left = record.get('comparison_profiles', {}).get(role, {}).get(key, [])
        for identity in witness.get('retained_by') or []:
            target = by_id.get(str(identity.get('trained_chara_id')))
            if not target or not target.get('selected_in_portfolio'):
                continue
            if target.get('comparison_group') != record.get('comparison_group'):
                continue
            right = target.get('comparison_profiles', {}).get(role, {}).get(key, [])
            if index >= len(left) or index >= len(right):
                continue
            try:
                l, r = float(left[index]), float(right[index])
                expected_l, expected_r = float(witness['candidate_score']), float(witness['replacement_score'])
                if not all(isfinite(v) for v in (l, r, expected_l, expected_r)):
                    continue
                if abs(l - expected_l) > 1e-5 or abs(r - expected_r) > 1e-5:
                    continue
            except (TypeError, ValueError, KeyError):
                continue
            valid.append(dict(witness, candidate_score=l, replacement_score=r,
                              delta=r-l, target=target, ace=aces[index], context=context))
            break
    valid.sort(key=lambda item: (item['delta'], item['context_key']))
    selected = []
    for role in ('parent', 'grandparent'):
        candidates = [w for w in valid if w['role'] == role]
        losses = [w for w in candidates if w['delta'] < -.005]
        practical = [w for w in candidates if all(
            int((w['ace'].get('target_aptitudes') or {}).get(d, {}).get('rank') or 0) >= 6
            for d in ('surface', 'distance', 'style'))]
        choice = losses or practical or candidates
        example = dict(choice[0], selection_kind='loss' if losses else 'practical' if practical else 'fallback') if choice else None
        if example:
            selected.append(example)
    return sorted(selected, key=lambda item: item['delta'])


def decision_html(record, examples, language, translate, expanded=False, *, model=None, focus=None, show_identity=True):
    t = translate
    if not record:
        return '<p>' + escape(t('Sélectionne une copie pour comprendre le verdict.')) + '</p>'
    status = record.get('status')
    reason = {
        'safe_transfer': 'Une copie conservée du même costume remplit les usages évalués de cette copie et préserve les facteurs que le moteur exige de garder.',
        'recommended_transfer': 'Cette copie n’est pas nécessaire à la sélection conservée : ses usages utiles sont repris par une ou plusieurs autres copies du même costume, dans la tolérance du modèle.',
        'keep': 'Cette copie participe à la sélection conservée pour préserver un usage ou un facteur requis. Un meilleur indice ailleurs ne suffit pas à la remplacer.',
        'protected': 'Cette copie est protégée. Son diagnostic de redondance ne constitue pas une proposition de transfert.',
        'review': 'Le rapport ne justifie pas suffisamment son remplacement. Cette copie reste à examiner.',
    }.get(status, 'Le rapport ne justifie pas suffisamment son remplacement. Cette copie reste à examiner.')
    if not show_identity:
        reason = {
            'safe_transfer': 'Un remplaçant conservé couvre les rôles évalués de cette copie.',
            'recommended_transfer': 'Ses rôles sont couverts par les copies conservées du même costume. Plusieurs remplaçants peuvent être nécessaires.',
            'keep': 'Elle préserve un rôle ou un facteur que les autres copies conservées ne remplacent pas assez bien.',
            'protected': 'Cette copie est protégée. Son diagnostic de redondance ne constitue pas une proposition de transfert.',
        }.get(status, reason)
    title = t('Pourquoi cette copie est proposée ?') if status in {'safe_transfer', 'recommended_transfer'} else t('Pourquoi ce verdict ?')
    html = ('<h2>' + escape(game_veteran_label(record)) + '</h2>') if show_identity else ''
    html += ('<h3>' + escape(title) + '</h3>' if show_identity else '') + '<p>' + escape(t(reason)) + '</p>'
    required = preserved_reasons(record, model, language, t)
    if status in {'keep', 'protected'} and required:
        html += '<p><b>' + escape(t('À préserver')) + ' :</b><br>' + '<br>'.join(escape(a) for a in required[:3]) + '</p>'
        if len(required) > 3:
            html += '<p>' + escape(t('{count} autres rôles ou facteurs à préserver.').replace('{count}', str(len(required)-3))) + '</p>'
    if examples:
        if show_identity:
            html += '<h3>' + escape(t('Vérifier avec des exemples')) + '</h3>'
        if show_identity:
            html += '<p>' + escape(t('Les pertes nettes sont prioritaires. Sinon, un Ace aux aptitudes utilisables est préféré. Chaque exemple compare le même Ace dans le même rôle.')) + '</p>'
        for index, w in enumerate(examples):
            if focus is not None and index != focus:
                continue
            context = w['context']
            prefix = t('Permanent') if context.get('scope') == 'permanent' else str(context.get('label') or w.get('profile') or '').split(' · ')[0]
            profile = ' · '.join(profile_label(kind, str(context[kind]), language)
                                 for kind in ('surface', 'distance', 'style') if context.get(kind))
            role = t('Parent' if w['role'] == 'parent' else 'Futur grand-parent')
            ace = str(w['ace'].get('card_name') or w['ace'].get('uma_name') or '—')
            if show_identity:
                html += '<p><b>' + escape(role + ' · ' + prefix + ' · ' + profile) + '</b><br>' + escape(t('Ace cible') + ' : ' + ace) + '<br>'
                identity = game_veteran_label(w['target'])
            else:
                html += '<p>'
                identity = game_rank_label(w['target'].get('rank')) + ' · ' + format_rank_score(w['target'].get('rank_score'))
            html += '<b>' + escape(t('Copie conservée') + ' : ' + identity) + '</b><br>'
            html += escape(t('Indice du modèle') + f" : {w['candidate_score']:.2f} → {w['replacement_score']:.2f} ({w['delta']:+.2f})") + '<br>'
            aptitudes = w['ace'].get('target_aptitudes') or {}
            if aptitudes and any(int(aptitudes.get(d, {}).get('rank') or 0) < 6
                                 for d in ('surface', 'distance', 'style')):
                html += '<b>' + escape(t('Profil exploratoire : aptitudes à relever')) + '</b><br>'
            if w['delta'] < -0.005:
                html += '<b>' + escape(t('Cette copie conserve un avantage ici : le modèle accepte cette perte limitée.')) + '</b><br>'
            html += '</p>'
            if model is not None:
                ace_index = next((i for i, ace in enumerate(w['context'].get('aces', []))
                                  if ace.get('card_id') == w.get('ace_card_id')), None)
                if ace_index is not None:
                    explanation = comparison_explanation(record, w['target'], model, w['context_key'], ace_index, w['role'])
                    html += explanation_html(explanation, t, compact=True)
            if show_identity:
                html += f'<p><a style="color:{COLORS["accent"]}" href="example:{index}">' + escape(t('Voir cet exemple dans la lignée')) + '</a></p>'
            else:
                html += '<p>' + escape(prefix + ' · ' + profile) + '<br>' + escape(t('Ace cible') + ' : ' + ace) + '</p>'
    elif status in {'safe_transfer', 'recommended_transfer'}:
        html += '<p>' + escape(t('Aucun exemple comparable n’est disponible dans ce rapport. Cette proposition reste à vérifier manuellement dans les détails avancés.')) + '</p>'
    if status in {'safe_transfer', 'recommended_transfer'}:
        html += '<p>' + escape(t('Avant de transférer : vérifie son usage en course et le coût de refaire ses facteurs. Le prototype ne les évalue pas.')) + '</p>'
    html += f'<p><a style="color:{COLORS["accent"]}" href="details:toggle">' + escape(t('Masquer les détails avancés' if expanded else 'Afficher les détails avancés')) + '</a></p>'
    return html

"""Two alternative branches, deliberately disconnected from each other."""
from html import escape

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from ui_qt.asset_catalog import trainee_portrait_url
from ui_qt.lineage_nodes import _node
from ui_qt.lineage_view import LineageTree
from ui_qt.theme import COLORS
from uma_legacy_linker.transfer_comparison import factor_identity
from uma_legacy_linker.veteran_identity import game_veteran_label, game_rank_label, format_rank_score


def comparison_nodes(
    records, role, history=False, skill_weights=None, spark_filter=None,
    spark_annotations=None,
):
    nodes = {}
    skill_weights = skill_weights or {}
    from uma_legacy_linker.skill_catalog import slugify
    for prefix, record in zip(('p1', 'p2'), records):
        member = record.get('comparison_veteran') or {}
        sources = [(prefix, member)]
        if role == 'parent' or history:
            lineage = member.get('when_used_as_parent') or {}
            sources += [(f'{prefix}-{i}', lineage.get(f'grandparent_{i}')) for i in (1, 2)]
        for position, source in sources:
            if not source:
                continue
            factors = [dict(factor, type=kind) for kind, values in
                       source.get('factors', {}).get('by_type', {}).items() for factor in values]
            if spark_filter is not None:
                factors = [factor for factor in factors if (
                    factor.get('type'), factor_identity(str(factor.get('type') or ''), factor)
                ) in spark_filter]
            annotations = spark_annotations or {}
            for factor in factors:
                identity = (
                    factor.get('type'),
                    factor_identity(str(factor.get('type') or ''), factor),
                )
                if identity in annotations:
                    factor.update(annotations[identity])
            node = _node(dict(source, card_name=source.get('card_name') or source.get('uma_name') or 'Nom indisponible', sparks=factors))
            for factor in node['sparks']:
                identity = (
                    factor.get('type'),
                    factor_identity(str(factor.get('type') or ''), factor),
                )
                if identity in (spark_annotations or {}):
                    factor.update(spark_annotations[identity])
            node['all_sparks'] = list(node['sparks'])
            # Short visual inventory; the accessible inspector retains every factor.
            essentials = [f for f in node['sparks'] if f['type'] in {'blue_stat', 'red_aptitude', 'unique'}]
            whites = sorted([f for f in node['sparks'] if f not in essentials],
                            key=lambda f: (-skill_weights.get(slugify(f['name']), 0) * f['stars'], f['name']))
            node['sparks'] = essentials + whites[:6]
            node['hidden_spark_count'] = max(0, len(whites) - 6)
            if node['hidden_spark_count']:
                node['sparks'].append({'name': f"+ {node['hidden_spark_count']}", 'stars': 0, 'type': 'other'})
            node['g1_names'] = source.get('g1_wins', {}).get('names', [])
            node['historical'] = role == 'grandparent' and '-' in position
            node['protected'] = bool(record.get('manual_protection_reasons')) if position == prefix else False
            nodes[position] = node
    totals = {}
    for prefix in ('p1', 'p2'):
        values = {}
        for position, node in nodes.items():
            if not position.startswith(prefix) or node.get('historical'):
                continue
            for factor in node['all_sparks']:
                key = factor['type'], factor_identity(str(factor['type']), factor)
                values[key] = values.get(key, 0) + factor['stars']
        totals[prefix] = values
    for position, node in nodes.items():
        if node.get('historical'):
            continue
        own, other = ('p1', 'p2') if position.startswith('p1') else ('p2', 'p1')
        for factor in node['all_sparks']:
            key = factor['type'], factor_identity(str(factor['type']), factor)
            factor['branch_star_delta'] = totals[own].get(key, 0) - totals[other].get(key, 0)
    return nodes


def node_detail_html(node, title, translate=lambda text: text):
    if not node:
        return ''
    text = '<b>' + escape(title) + ' · ' + escape(game_veteran_label(node)) + '</b>'
    if node.get('historical'):
        text += '<p>' + escape(translate('Historique du farm · exclu du score GP. Le coût de reproduction reste inconnu.')) + '</p>'
    if node.get('protected'):
        text += '<p>' + escape(translate('Protégé — diagnostic seulement')) + '</p>'
    text += '<p>' + ' · '.join(
        escape(f"{f['name']} {f['stars']}★" + (" · " + translate("Inactif") if f.get('is_inactive') else ""))
        for f in node.get('all_sparks', [])
    ) + '</p>'
    names = node.get('g1_names', [])
    return text + '<p>G1 : ' + (', '.join(escape(n) for n in names) or escape(translate('Aucune donnée'))) + '</p>'


class TransferLineageTree(LineageTree):
    node_selected = Signal(str)
    BASE_WIDTH = 1160
    MAX_LAYOUT_WIDTH = 1920

    def __init__(self, context, repository, parent=None, zoom=0.75):
        self.selected_node = None
        super().__init__(context, {}, repository, mode='transfer', zoom=zoom, parent=parent)

    def retranslate(self):
        t = self.context.t
        self._role_labels = {key: t(label) for key, label in {
            'p1': 'Copie étudiée', 'p2': 'Copie comparée',
            'p1-1': 'GP A · branche étudiée', 'p1-2': 'GP B · branche étudiée',
            'p2-1': 'GP A · branche comparée', 'p2-2': 'GP B · branche comparée',
        }.items()}
        self._base_role_labels = dict(self._role_labels)
        self.setAccessibleName(t('Comparaison de deux branches alternatives'))
        self.update()

    def set_selected_node(self, position):
        self.selected_node = position
        self.update()

    def set_nodes(self, nodes):
        self.setVisible(bool(nodes))
        self.nodes = nodes
        self.setAccessibleDescription(' · '.join(game_veteran_label(n) for n in nodes.values()))
        self.refresh_images()
        self.updateGeometry()

    def refresh_images(self):
        self._pixmaps.clear()
        self._node_urls.clear()
        self._skill_urls.clear()
        for position, node in self.nodes.items():
            url = trainee_portrait_url(node.get('card_id'))
            if url:
                self._node_urls[position] = url
                self._request_pixmap(url)
        self.update()

    def _schedule_height(self, height):
        required = max(220, int(height + 1))
        self._scheduled_minimum_height = required
        if abs(self._logical_height - required) > 1 and not self._height_update_pending:
            self._height_update_pending = True
            self._height_timer.start(0)

    def _layout_rects(self):
        width = min(self._logical_canvas_width(), self.MAX_LAYOUT_WIDTH)
        origin = (self._logical_canvas_width() - width) / 2
        rects = {}
        prefixes = [prefix for prefix in ('p1', 'p2') if prefix in self.nodes]
        if not prefixes:
            return rects
        branch_width = (width - 100) / 2 if len(prefixes) == 2 else width - 64
        parent_width = branch_width * .94
        parent_height = max(self._card_height(p, parent_width) for p in prefixes)
        gp_width = (branch_width - 20) / 2
        gp_height = max((self._card_height(p, gp_width) for p in self.nodes if '-' in p), default=0)
        for i, prefix in enumerate(prefixes):
            left = (
                origin + 32 + i * (branch_width + 36)
                if len(prefixes) == 2 else origin + 32
            )
            rects[prefix] = QRectF(left + (branch_width-parent_width)/2, 42, parent_width, parent_height)
            for j in (1, 2):
                position = f'{prefix}-{j}'
                if position in self.nodes:
                    rects[position] = QRectF(left + (j-1)*(gp_width+20), 42+parent_height+72, gp_width, gp_height)
        self._schedule_height(max(r.bottom() for r in rects.values()) + 36)
        return rects

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(COLORS['background']))
        painter.scale(self._zoom, self._zoom)
        rects = self._layout_rects()
        self._card_rects, self._spark_rects = rects, []
        for prefix, color in (('p1', '#426e65'), ('p2', '#46658f')):
            if prefix in rects:
                self._draw_branch(painter, rects[prefix], [rects[p] for p in (f'{prefix}-1', f'{prefix}-2') if p in rects], color)
        for position, rect in rects.items():
            self._draw_card(painter, position, rect, self.nodes.get(position))
            if position == self.selected_node:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(COLORS['focus']), 3))
                painter.drawRoundedRect(rect.adjusted(-3, -3, 3, 3), 12, 12)

    def _draw_card(self, painter, position, rect, node):
        if node:
            # The inherited renderer uses card_id as text. Keep it exclusively
            # in image lookup and replace metadata with the actual game identity.
            node = dict(node, card_id=None, rank=None,
                        uma_name=f"{game_rank_label(node.get('rank'))} · {format_rank_score(node.get('rank_score'))}")
            if node.get('historical'):
                self._role_labels[position] = self.context.t('Historique · hors score GP')
            elif node.get('protected'):
                self._role_labels[position] = self._base_role_labels[position] + ' · ' + self.context.t('Protégé')
        super()._draw_card(painter, position, rect, node)

    def _draw_node_image(self, painter, position, rect, node):
        super()._draw_node_image(painter, position, rect, self.nodes.get(position) or node)

    def _card_tooltip(self, position):
        node = self.nodes.get(position, {})
        return game_veteran_label(node) + '\n' + self.context.t('Cliquer pour inspecter tous les facteurs.')

    def _draw_spark_chip(self, painter, position, index, rect, factor):
        super()._draw_spark_chip(painter, position, index, rect, factor)
        if factor.get('is_inactive'):
            return
        delta = factor.get('branch_star_delta', 0)
        if delta:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#78d6ad' if delta > 0 else '#ff8e98'), 1.8))
            painter.drawRoundedRect(rect, 5, 5)

    def _spark_tooltip(self, factor):
        text = f"{factor.get('name', '—')} · {factor.get('stars', 0)}★"
        if factor.get('is_inactive') and factor.get('inactive_reason'):
            text += "\n" + self.context.t(str(factor["inactive_reason"]))
        if factor.get('branch_star_delta'):
            text += "\n" + self.context.t("Écart total dans cette branche : {delta}★. Ce contour ne mesure pas les points du modèle.").replace("{delta}", f"{factor['branch_star_delta']:+}")
        return text

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.logical_position(event.position())
            for position, rect in self._card_rects.items():
                if rect.contains(point):
                    self.node_selected.emit(position)
                    return
        super().mousePressEvent(event)

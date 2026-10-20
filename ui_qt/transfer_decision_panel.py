"""Identity and role navigation stay visible while evidence can be scrolled."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTabBar, QTextBrowser, QVBoxLayout, QWidget, QPushButton

from ui_qt.asset_catalog import trainee_portrait_url
from ui_qt.image_assets import image_repository
from ui_qt.typography import css_point_size
from uma_legacy_linker.veteran_identity import format_rank_score, game_rank_label, game_veteran_label


class TransferDecisionPanel(QWidget):
    example_changed = Signal(int)
    verification_requested = Signal(int)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.setMinimumWidth(340)
        self._record = None
        self._portrait_url = None
        self.repository = image_repository(context)
        self.repository.image_ready.connect(self._image_ready)
        self.repository.cache_changed.connect(self._refresh_portrait)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.portrait = QLabel()
        self.portrait.setFixedSize(58, 66)
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.portrait)
        identity = QVBoxLayout()
        self.name = QLabel()
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setWordWrap(True)
        self.name.setMaximumHeight(48)
        self.rank_score = QLabel()
        self.rank_score.setStyleSheet(f"font-size: {css_point_size('heading')}; font-weight: 700;")
        self.badge = QLabel()
        self.badge.setWordWrap(True)
        self.badge.setTextFormat(Qt.TextFormat.PlainText)
        identity.addWidget(self.name)
        identity.addWidget(self.rank_score)
        identity.addWidget(self.badge)
        header.addLayout(identity, 1)
        root.addLayout(header)
        self.family_summary = QLabel()
        self.family_summary.setObjectName('muted')
        self.family_summary.setWordWrap(True)
        root.addWidget(self.family_summary)
        self.examples = QTabBar()
        self.examples.setExpanding(True)
        self.examples.currentChanged.connect(self.example_changed)
        root.addWidget(self.examples)
        self.browser = QTextBrowser()
        self.browser.document().setDefaultStyleSheet('p { margin-top: 4px; margin-bottom: 8px; } h3 { margin-top: 8px; margin-bottom: 4px; }')
        self.browser.setOpenLinks(False)
        root.addWidget(self.browser, 1)
        self.verify_button = QPushButton()
        self.verify_button.setObjectName('primary')
        self.verify_button.clicked.connect(lambda: self.verification_requested.emit(self.examples.currentIndex()))
        self.actions_layout = QHBoxLayout()
        self.actions_layout.addWidget(self.verify_button, 1)
        root.addLayout(self.actions_layout)

    def set_identity(self, record, records, examples, selected):
        t = self.context.t
        self._record = record
        self.name.setText(str((record or {}).get('card_name') or (record or {}).get('uma_name') or '—'))
        self.rank_score.setText(game_rank_label((record or {}).get('rank')) + ' · '
                                + format_rank_score((record or {}).get('rank_score')))
        self.name.setToolTip(game_veteran_label(record))
        statuses = {'safe_transfer': 'Équivalent dans le modèle', 'recommended_transfer': 'Redondant dans le modèle',
                    'keep': 'Conserver', 'review': 'À examiner', 'protected': 'Protégé'}
        status = (record or {}).get('status')
        badge = t(statuses.get(status, 'Aucun rapport affiché'))
        if status == 'protected' and (record or {}).get('analysis_status') in {'safe_transfer', 'recommended_transfer'}:
            badge += ' · ' + t('Redondant') + ' · ' + t('Protégé — diagnostic seulement')
        self.badge.setText(badge)
        group = (record or {}).get('comparison_group')
        family = [r for r in records if group and r.get('comparison_group') == group]
        kept = sum(bool(r.get('selected_in_portfolio')) for r in family)
        family_text = ''
        if family:
            family_text = t('{kept} copies conservées sur {total} pour ce costume.').replace(
                '{kept}', str(kept)).replace('{total}', str(len(family))) if all(
                    'selected_in_portfolio' in r for r in family) else t('{total} copies de ce costume.').replace('{total}', str(len(family)))
        self.family_summary.setText(family_text)
        self.examples.blockSignals(True)
        while self.examples.count():
            self.examples.removeTab(0)
        for example in examples:
            role = t('Parent' if example['role'] == 'parent' else 'Futur grand-parent')
            if example['delta'] < -.005:
                role += ' · ' + t('Perte à vérifier')
            self.examples.addTab(role)
            self.examples.setTabToolTip(self.examples.count()-1, t('Pertes nettes prioritaires, puis cas aux aptitudes utilisables. Ces exemples ne démontrent pas toute la couverture à eux seuls.'))
        self.examples.setCurrentIndex(max(0, min(selected, len(examples)-1)))
        self.examples.setVisible(bool(examples))
        self.verify_button.setText(t('Vérifier cet exemple…'))
        self.verify_button.setVisible(bool(examples))
        self.examples.setAccessibleName(t('Exemples pour vérifier le verdict'))
        self.examples.blockSignals(False)
        self._portrait_url = trainee_portrait_url((record or {}).get('card_id'))
        self._refresh_portrait()

    def _refresh_portrait(self):
        self.portrait.clear()
        self.portrait.setText('—')
        if self._portrait_url:
            pixmap = self.repository.pixmap(self._portrait_url)
            if pixmap is not None:
                self._image_ready(self._portrait_url, pixmap)
            else:
                self.repository.request(self._portrait_url)

    def _image_ready(self, url, pixmap):
        if url == self._portrait_url:
            self.portrait.setPixmap(pixmap.scaled(self.portrait.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))

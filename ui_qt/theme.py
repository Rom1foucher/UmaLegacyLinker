from __future__ import annotations


COLORS = {
    "background": "#0b1018",
    "sidebar": "#0f1622",
    "surface": "#141d2b",
    "surface_alt": "#192536",
    "border": "#25344a",
    "text": "#edf4ff",
    "muted": "#91a3bb",
    "accent": "#68d3b1",
    "accent_hover": "#7de3c1",
    "accent_dark": "#173f39",
    "blue": "#70a8ff",
    "warning": "#f2c166",
    "danger": "#ff7b88",
}

# background, border and foreground for compact Spark chips.  Kept beside the
# main palette so contrast can be audited without importing the Qt runtime.
SPARK_COLORS = {
    "blue_stat": ("#0d304d", "#286da3", "#83c7ff"),
    "red_aptitude": ("#3a1424", "#7f294a", "#ff8bb0"),
    "unique": ("#14351f", "#397848", "#8cdd9a"),
    "white_skill": ("#2b3037", "#59636f", "#e1e8f0"),
    "white_race": ("#292e35", "#58616c", "#d9e0e8"),
    # Useful profile-compatible whites get a visible but deliberately quieter
    # treatment than the very strongest contributors.  This lets the result
    # view surface more than an arbitrary top three without turning the whole
    # Spark list gold.
    "white_useful": ("#132d3b", "#397896", "#bfe9ff"),
    "white_priority": ("#352b12", "#d5aa3f", "#ffe9a3"),
    # Scenario Sparks are informative/stat-oriented, not automatically major
    # white priorities.  A muted violet keeps them distinct from both ordinary
    # race whites and the gold priority treatment.
    "scenario": ("#26243a", "#5d5984", "#cbc7f4"),
    "other": ("#252b34", "#4b5869", "#cbd6e4"),
}

APTITUDE_COLORS = {
    "header_background": "#347f1b",
    "header_foreground": "#f5fff0",
    "cell_background": "#f4f0de",
    "cell_foreground": "#4a3424",
    "name": "#5a3b27",
    "S": "#9a6500",
    "A": "#b3470d",
    "B": "#a92e62",
    "C": "#387527",
    "D": "#27689d",
    "other": "#6c6870",
}

# background, border and foreground for the game-inspired aptitude rank
# emblems.  These are intentionally drawn with Qt rich text instead of raster
# assets so they remain crisp at every Windows scaling factor.
RANK_BADGE_COLORS = {
    "S": ("#e6b72c", "#7a5200", "#2b1b00"),
    "A": ("#b84b17", "#74300e", "#fff7ec"),
    "B": ("#9b2b59", "#661a39", "#fff4f8"),
    "C": ("#39772b", "#23551a", "#f6fff1"),
    "D": ("#2d6f9f", "#1b4c72", "#f2f9ff"),
    "E": ("#5c4b99", "#3d326d", "#faf7ff"),
    "F": ("#4b426e", "#302947", "#f8f6ff"),
    "G": ("#555d68", "#343a42", "#ffffff"),
    "unknown": ("#59616d", "#363d46", "#ffffff"),
}


def application_stylesheet() -> str:
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 10pt;
        color: {COLORS['text']};
    }}
    QMainWindow, QWidget#root {{
        background: {COLORS['background']};
    }}
    QDialog, QMessageBox {{
        background: {COLORS['background']};
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}
    QFrame#sidebar {{
        background: {COLORS['sidebar']};
        border-right: 1px solid {COLORS['border']};
    }}
    QLabel#brand {{
        font-size: 17pt;
        font-weight: 700;
        color: {COLORS['text']};
    }}
    QLabel#navSection {{
        color: #72849d;
        font-size: 8pt;
        font-weight: 700;
        padding: 4px 10px 0 10px;
    }}
    QLabel#versionBadge {{
        background: {COLORS['accent_dark']};
        color: {COLORS['accent']};
        border: 1px solid #2a6659;
        border-radius: 9px;
        padding: 3px 8px;
        font-size: 8.5pt;
        font-weight: 600;
    }}
    QLabel#pageTitle {{
        font-size: 22pt;
        font-weight: 700;
    }}
    QLabel#pageSubtitle, QLabel#muted, QLabel#cardDetail {{
        color: {COLORS['muted']};
    }}
    QLabel#sectionTitle {{
        font-size: 12pt;
        font-weight: 650;
    }}
    QLabel#settingSummary {{
        color: #dce9f8;
        font-size: 11pt;
        padding: 2px 1px 5px 1px;
    }}
    QLabel#pill, QLabel#pillAccent, QLabel#pillWarning {{
        border-radius: 9px;
        padding: 3px 8px;
        font-size: 8.5pt;
        font-weight: 650;
    }}
    QLabel#pill {{
        color: #b7c6d9;
        background: #1a2738;
        border: 1px solid #30445e;
    }}
    QLabel#pillAccent {{
        color: #8de8ca;
        background: #173b36;
        border: 1px solid #2a6659;
    }}
    QLabel#pillWarning {{
        color: #f7d487;
        background: #3b301b;
        border: 1px solid #69552a;
    }}
    QLabel#metric {{
        font-size: 18pt;
        font-weight: 700;
    }}
    QFrame#card, QFrame#panel, QGroupBox {{
        background: {COLORS['surface']};
        border: 1px solid {COLORS['border']};
        border-radius: 10px;
    }}
    QFrame#subtlePanel {{
        background: #101824;
        border: 1px solid #223149;
        border-radius: 8px;
    }}
    QFrame#infoCallout {{
        background: #112331;
        border: 1px solid #294a60;
        border-radius: 8px;
    }}
    QLabel#calloutTitle {{
        color: {COLORS['blue']};
        font-weight: 700;
    }}
    QGroupBox {{
        margin-top: 13px;
        padding: 16px 12px 12px 12px;
        font-weight: 650;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 5px;
    }}
    QPushButton {{
        background: {COLORS['surface_alt']};
        border: 1px solid {COLORS['border']};
        border-radius: 7px;
        padding: 8px 13px;
        font-weight: 550;
    }}
    QPushButton:hover {{
        background: #213149;
        border-color: #3a5273;
    }}
    QPushButton:pressed {{
        background: #101a27;
    }}
    QPushButton:focus {{
        border-color: {COLORS['accent']};
    }}
    QPushButton:disabled {{
        color: #647287;
        background: #111823;
        border-color: #202b3c;
    }}
    QPushButton#primary {{
        color: #07120f;
        background: {COLORS['accent']};
        border-color: {COLORS['accent']};
        font-weight: 700;
    }}
    QPushButton#primary:hover {{
        background: {COLORS['accent_hover']};
    }}
    QPushButton#nav {{
        background: transparent;
        border: none;
        border-radius: 7px;
        padding: 8px 11px;
        text-align: left;
        color: {COLORS['muted']};
        font-weight: 550;
    }}
    QPushButton#nav:hover {{
        color: {COLORS['text']};
        background: #172234;
    }}
    QPushButton#nav:checked {{
        color: {COLORS['accent']};
        background: {COLORS['accent_dark']};
        border-left: 3px solid {COLORS['accent']};
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: #0f1723;
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 7px 9px;
        selection-background-color: #2b675b;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {COLORS['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: #647287;
        background: #111823;
        border-color: #202b3c;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background: {COLORS['surface_alt']};
        border: 1px solid {COLORS['border']};
        selection-background-color: #27564f;
    }}
    QCheckBox {{
        spacing: 7px;
        color: {COLORS['text']};
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid #40536d;
        border-radius: 4px;
        background: #0f1723;
    }}
    QCheckBox::indicator:checked {{
        background: {COLORS['accent']};
        border-color: {COLORS['accent']};
    }}
    QSlider::groove:horizontal {{
        height: 6px;
        background: #26364d;
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {COLORS['accent']};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        width: 17px;
        height: 17px;
        margin: -6px 0;
        background: #d9fff3;
        border: 2px solid {COLORS['accent']};
        border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{
        background: #ffffff;
        border-color: {COLORS['accent_hover']};
    }}
    QSlider:disabled {{
        background: transparent;
    }}
    QListWidget {{
        background: #101824;
        alternate-background-color: #131e2d;
        border: 1px solid {COLORS['border']};
        border-radius: 7px;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 7px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: #28584f;
    }}
    QTabWidget::pane {{
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
        background: {COLORS['surface']};
        top: -1px;
    }}
    QTabBar::tab {{
        color: {COLORS['muted']};
        background: transparent;
        padding: 9px 14px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{
        color: {COLORS['accent']};
        border-bottom-color: {COLORS['accent']};
    }}
    QTableView {{
        background: #101824;
        alternate-background-color: #131e2d;
        border: none;
        gridline-color: #223149;
        selection-background-color: #28584f;
        selection-color: {COLORS['text']};
    }}
    QTreeWidget#weightsTree {{
        background: #101824;
        alternate-background-color: #121c2a;
        border: 1px solid #223149;
        border-radius: 8px;
        outline: none;
        padding: 3px;
    }}
    QTreeWidget#weightsTree::item {{
        min-height: 25px;
        padding: 2px 5px;
        border-bottom: 1px solid #1b2839;
    }}
    QTreeWidget#weightsTree::item:hover {{
        background: #1a2a3d;
    }}
    QTreeWidget#weightsTree::item:selected {{
        background: #28584f;
        color: {COLORS['text']};
    }}
    QTreeWidget#weightsTree::branch {{
        background: transparent;
    }}
    QFrame#weightsToolbar {{
        background: #121c29;
        border: 1px solid #223149;
        border-radius: 9px;
    }}
    QFrame#weightsNavigationPanel, QFrame#weightsEditorPanel {{
        background: {COLORS['surface']};
        border: 1px solid {COLORS['border']};
        border-radius: 10px;
    }}
    QHeaderView::section {{
        background: #182436;
        color: #bdd0e7;
        border: none;
        border-right: 1px solid #263751;
        border-bottom: 1px solid #263751;
        padding: 8px 7px;
        font-weight: 650;
    }}
    QTableCornerButton::section {{
        background: #182436;
        border: none;
        border-right: 1px solid #263751;
        border-bottom: 1px solid #263751;
    }}
    QTextBrowser, QPlainTextEdit {{
        background: #0f1723;
        border: 1px solid {COLORS['border']};
        border-radius: 7px;
        padding: 8px;
    }}
    QToolButton {{
        color: {COLORS['text']};
        background: transparent;
    }}
    QMenu {{
        color: {COLORS['text']};
        background: {COLORS['surface_alt']};
        border: 1px solid {COLORS['border']};
    }}
    QMenu::item:selected {{ background: #28584f; }}
    QProgressBar {{
        background: #101824;
        border: 1px solid {COLORS['border']};
        border-radius: 5px;
        text-align: center;
        min-height: 8px;
        max-height: 8px;
    }}
    QProgressBar::chunk {{
        background: {COLORS['accent']};
        border-radius: 4px;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 11px;
        margin: 1px;
    }}
    QScrollBar::handle:vertical {{
        background: #34475f;
        border-radius: 5px;
        min-height: 24px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 11px;
        margin: 1px;
    }}
    QScrollBar::handle:horizontal {{
        background: #34475f;
        border-radius: 5px;
        min-width: 24px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QSplitter::handle {{
        background: {COLORS['border']};
    }}
    QToolTip {{
        color: {COLORS['text']};
        background: {COLORS['surface_alt']};
        border: 1px solid {COLORS['border']};
        padding: 5px;
    }}
    """

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPainter, QPixmap, QTextTable
from PySide6.QtWidgets import (
    QApplication,
    QAbstractButton,
    QCheckBox,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStyle,
    QStyleOptionButton,
    QTextBrowser,
    QWidget,
)

from ui_qt.components import CollapsibleSection
from ui_qt.context import AppContext
from ui_qt.core import SettingsStore
from ui_qt.lineage_view import LineageDialog
from ui_qt.main_window import MainWindow
from ui_qt.pages_online import OnlineResultsPane
from ui_qt.pages_optimizer import ResultPane
from ui_qt.presentation import online_detail_html, result_detail_html
from ui_qt.theme import application_stylesheet


SIZES = ((1120, 720), (1366, 768), (1600, 900))


def _dispose_widget(widget: QWidget, application: QApplication) -> None:
    """Destroy an audit top-level before its shared Qt dependencies.

    ``close()`` only hides widgets by default.  Keeping the lineage dialogs
    alive until interpreter shutdown also keeps their timers and connections
    to the context-owned image repository alive.  PySide/Qt can then destroy
    that graph in an unsafe order on Windows' offscreen platform.
    """

    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


def _widget_name(widget: QWidget) -> str:
    name = widget.objectName() or widget.metaObject().className()
    text = ""
    if isinstance(widget, (QLabel, QAbstractButton)):
        text = widget.text().replace("\n", " / ").strip()
    return f"{name} [{text[:80]}]" if text else name


def _button_text_width(button: QAbstractButton) -> int:
    """Return the width Qt actually leaves for a button's text.

    A fixed padding estimate is inaccurate with Qt style sheets: Fusion,
    Windows and the offscreen platform can all expose different content
    margins.  Asking the active style for its content rectangle mirrors the
    geometry used when the control is painted.
    """

    option = QStyleOptionButton()
    option.initFrom(button)
    option.text = button.text()
    option.icon = button.icon()
    if isinstance(button, QCheckBox):
        element = QStyle.SubElement.SE_CheckBoxContents
    elif isinstance(button, QRadioButton):
        element = QStyle.SubElement.SE_RadioButtonContents
    elif isinstance(button, QPushButton):
        element = QStyle.SubElement.SE_PushButtonContents
    else:
        return button.contentsRect().width()
    contents = button.style().subElementRect(element, option, button)
    available = contents.width()
    if not button.icon().isNull():
        available -= button.iconSize().width() + 4
    return max(0, available)


def _plain_button_text(text: str) -> str:
    """Strip mnemonic markers while preserving escaped ampersands."""

    placeholder = "\0"
    return text.replace("&&", placeholder).replace("&", "").replace(placeholder, "&")


def _text_overflow(widget: QWidget) -> bool:
    if not widget.isVisible() or widget.width() < 24:
        return False
    if isinstance(widget, QLabel):
        text = widget.text()
        if not text or widget.wordWrap() or "\n" in text or widget.textFormat() == Qt.TextFormat.RichText:
            return False
        required = widget.fontMetrics().horizontalAdvance(text)
        return required > widget.contentsRect().width()
    if isinstance(widget, QAbstractButton):
        text = _plain_button_text(widget.text())
        if not text or "\n" in text:
            return False
        required = widget.fontMetrics().horizontalAdvance(text)
        return required > _button_text_width(widget)
    return False


def audit_window(window: QWidget) -> list[str]:
    issues: list[str] = []
    for widget in window.findChildren(QWidget):
        if not widget.isVisibleTo(window):
            continue
        if _text_overflow(widget):
            issues.append(f"text overflow: {_widget_name(widget)} ({widget.width()} px)")
        if isinstance(widget, QScrollArea) and widget.widgetResizable() and widget.widget():
            viewport_width = widget.viewport().width()
            content_width = widget.widget().width()
            if (
                widget.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
                and content_width > viewport_width + 3
            ):
                issues.append(
                    f"hidden horizontal overflow: {_widget_name(widget)} "
                    f"({content_width} > {viewport_width} px)"
                )
        if isinstance(widget, QTextBrowser) and widget.viewport().width() >= 400:
            layout = widget.document().documentLayout()
            available = widget.viewport().width()
            for frame in widget.document().rootFrame().childFrames():
                if not isinstance(frame, QTextTable):
                    continue
                rendered_width = layout.frameBoundingRect(frame).width()
                if rendered_width < available * 0.72:
                    issues.append(
                        f"underfilled rich-text table: {_widget_name(widget)} "
                        f"({rendered_width:.0f} < {available * 0.72:.0f} px)"
                    )
    return sorted(set(issues))


def run_audit(output_dir: Path) -> dict[str, object]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    application = QApplication.instance() or QApplication([])
    application.setStyle("Fusion")
    application.setStyleSheet(application_stylesheet())
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"screens": [], "issues": []}
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        store = SettingsStore(temp / "config.json")
        store.update(
            {
                "output_dir": str(temp / "output"),
                "ui_language": "fr",
                "online_images": "0",
            }
        )
        context = AppContext(store)
        window = MainWindow(context)
        window.show()
        application.processEvents()
        for section in window.findChildren(CollapsibleSection):
            section.toggle.setChecked(True)
        for language in ("fr", "en"):
            window.context.set_language(language)
            for page in window._nav_order:  # intentional internal QA hook
                window.show_page(page)
                application.processEvents()
                variants: list[tuple[str, str | None]] = [(page, None)]
                current_page = window._pages[page]
                if page == "search" and hasattr(current_page, "set_rail_collapsed"):
                    # The rail is the page's main layout state: both positions
                    # have to survive every audited width.
                    variants = [
                        ("search", "rail-expanded"),
                        ("search-rail-collapsed", "rail-collapsed"),
                        ("search-options-parent", "options-parent"),
                        ("search-options-grandparent", "options-grandparent"),
                    ]
                if page == "weights" and hasattr(current_page, "_all_rows"):
                    variants = [
                        ("weights-distribution", "distribution"),
                        ("weights-probability", "probability"),
                        ("weights-multiplier", "multiplier"),
                        ("weights-boolean", "boolean"),
                        ("weights-advanced", "advanced"),
                    ]
                for variant, mode in variants:
                    print(f"Auditing {language}/{variant}...", flush=True)
                    if page == "search" and mode is not None:
                        current_page.set_rail_collapsed(
                            mode == "rail-collapsed", persist=False
                        )
                        if mode.startswith("options-"):
                            # Replaces the former per-mode option dialogs: the
                            # same controls, audited where they now live.
                            focus = (
                                current_page.section_online_parent
                                if mode == "options-parent"
                                else current_page.section_online_gp
                            )
                            for section in (
                                current_page.section_objective,
                                current_page.section_course,
                                current_page.section_conditions,
                                current_page.section_online_parent,
                                current_page.section_online_gp,
                            ):
                                section.toggle.setChecked(section is focus)
                            current_page.section_retrieval.toggle.setChecked(True)
                            application.processEvents()
                            current_page.rail_scroll.ensureWidgetVisible(focus)
                        application.processEvents()
                    if page == "weights" and mode is not None:
                        if mode == "distribution":
                            row = next(
                                item
                                for item in current_page._all_rows
                                if item["path_tuple"][:2]
                                == ("mode_weights", "parent_pair")
                            )
                        elif mode == "probability":
                            row = next(
                                item
                                for item in current_page._all_rows
                                if item["path_tuple"]
                                == ("white_inheritance", "base_proc_rates", "3")
                            )
                        elif mode == "multiplier":
                            row = next(
                                item
                                for item in current_page._all_rows
                                if item["path_tuple"]
                                == (
                                    "blue_stat_weights_by_distance",
                                    "long",
                                    "Stamina",
                                )
                            )
                        elif mode == "boolean":
                            row = next(
                                item
                                for item in current_page._all_rows
                                if item["path_tuple"]
                                == ("transfer_helper", "include_course_presets")
                            )
                        else:
                            row = next(
                                item
                                for item in current_page._all_rows
                                if item["help"].advanced
                            )
                        current_page._show_selection(row)
                        application.processEvents()
                    for width, height in SIZES:
                        # Recreate the offscreen backing store between sizes.
                        # Otherwise QScrollArea viewports can leave stale pixels
                        # after the preceding 1600px capture is shrunk to 1120px.
                        window.hide()
                        window.resize(width, height)
                        window.show()
                        application.processEvents()
                        name = f"{language}-{variant}-{width}x{height}.png"
                        target = output_dir / name
                        if page == "tools":
                            # A fresh top-level avoids stale QScrollArea backing
                            # pixels in Qt's offscreen plugin at the smallest
                            # size. It uses the same context and page state.
                            capture_window = MainWindow(context)
                            capture_window.show_page("tools")
                            capture_window.resize(width, height)
                            capture_window.show()
                            application.processEvents()
                            capture = capture_window.grab()
                            _dispose_widget(capture_window, application)
                        else:
                            capture = window.grab()
                            # Composite the fixed sidebar from a fresh direct
                            # render after repeated offscreen resizes.
                            sidebar_capture = QPixmap(window.sidebar.size())
                            sidebar_capture.fill(Qt.GlobalColor.transparent)
                            window.sidebar.render(sidebar_capture)
                            painter = QPainter(capture)
                            painter.drawPixmap(window.sidebar.pos(), sidebar_capture)
                            painter.end()
                        capture.save(str(target), "PNG")
                        issues = audit_window(window)
                        entry = {
                            "language": language,
                            "page": variant,
                            "size": [width, height],
                            "screenshot": name,
                            "issues": issues,
                        }
                        report["screens"].append(entry)
                        for issue in issues:
                            report["issues"].append(f"{language}/{variant}/{width}x{height}: {issue}")

            def member(card_id: int, name: str, blue: int, pink: int) -> dict[str, object]:
                shared_whites = (
                    "Uma Stan",
                    "Nimble Navigator",
                    "Tail Held High",
                    "Corner Adept",
                    "Straightaway Recovery",
                    "Firm Conditions ○",
                )
                extra_whites = (
                    f"Long diagnostic skill {card_id % 7 + 1}",
                    f"Race Spark {card_id % 11 + 1}",
                )
                return {
                    "card_id": card_id,
                    "uma_name": name,
                    "card_name": f"{name} — Costume with a deliberately useful label",
                    "g1_count": 7,
                    "sparks": [
                        {"name": "Speed", "stars": blue, "type": "blue_stat"},
                        {"name": "Medium", "stars": pink, "type": "red_aptitude"},
                        {
                            "name": f"{name} Unique",
                            "stars": 2,
                            "type": "unique",
                        },
                    ]
                    + [
                        {
                            "name": white_name,
                            "stars": 1 + (index % 3),
                            "type": "white_skill",
                            "skill_id": 10011 + index,
                            "proc_probability_over_run": 0.12 + index * 0.018,
                            "is_score_priority": index < 2,
                            "is_score_useful": 2 <= index < 5,
                            "score_priority_rank": index + 1 if index < 2 else 999,
                        }
                        for index, white_name in enumerate(
                            shared_whites + extra_whites
                        )
                    ],
                }

            preview = {
                "p1": member(100701, "Gold Ship", 3, 2),
                "p2": member(101301, "Mejiro McQueen", 2, 3),
                "p1-1": member(100101, "Special Week", 3, 1),
                "p1-2": member(100201, "Silence Suzuka", 2, 2),
                "p2-1": member(100301, "Tokai Teio", 1, 3),
                "p2-2": member(100401, "Maruzensky", 3, 3),
            }
            preview.update(
                {
                    position: member(101000 + index * 100, f"History {index}", 2, 1)
                    for index, position in enumerate(
                        (
                            "p1-1-1",
                            "p1-1-2",
                            "p1-2-1",
                            "p1-2-2",
                            "p2-1-1",
                            "p2-1-2",
                            "p2-2-1",
                            "p2-2-2",
                        ),
                        1,
                    )
                }
            )
            lineage_row = {
                "score": 87.42,
                "parent_1": preview["p1"],
                "parent_2": preview["p2"],
                "lineage_preview": preview,
                "affinity": {
                    "total": 293,
                    "base": 110,
                    "g1_bonus": 183,
                    "parent_parent_base": 20,
                    "inheritance_affinities": {
                        "values": {
                            "parent_1": 164,
                            "parent_2": 151,
                            "parent_1_grandparent_1": 42,
                            "parent_1_grandparent_2": 39,
                            "parent_2_grandparent_1": 46,
                            "parent_2_grandparent_2": 41,
                        }
                    },
                },
                "component_details": {
                    "white_skill": {
                        "inspiration_event_count": 2,
                        "top_skills": [
                            {
                                "name": "Corner Adept",
                                "catalog_key": "corner_adept",
                                "profile_weight": 0.8,
                                "contribution": 0.42,
                            }
                        ],
                        "factors": [
                            {
                                "role": role,
                                "source_type": "white_skill",
                                "source_factor_name": "Corner Adept",
                                "name": "Corner Adept",
                                "catalog_key": "corner_adept",
                                "stars": 1,
                                "proc_probability_over_run": probability,
                            }
                            for role, probability in (
                                ("parent_1", 0.246576),
                                ("parent_2", 0.235000),
                                ("parent_1_grandparent_1", 0.164000),
                                ("parent_1_grandparent_2", 0.158000),
                                ("parent_2_grandparent_1", 0.169000),
                                ("parent_2_grandparent_2", 0.166000),
                            )
                        ],
                    }
                },
                "distance_viability": {"key": "ready_for_s", "tier": 4},
                "distance_s_summary": {
                    "base_rank_label": "A",
                    "initial_rank_label": "A",
                    "total_stars": 9,
                    "carrier_count": 4,
                    "parent_carrier_count": 1,
                    "procs_required_for_a": 0,
                    "procs_required_for_s": 1,
                    "probability_reach_a": 1.0,
                    "probability_reach_s": 0.404,
                },
                "aptitude_summaries": {
                    "surface": {
                        "base_rank_label": "B",
                        "initial_rank_label": "A",
                        "probability_reach_s": 0.35,
                    },
                    "style": {
                        "base_rank_label": "A",
                        "initial_rank_label": "A",
                        "probability_reach_s": 0.13,
                    },
                },
            }
            target_ace = {
                "card_id": 103101,
                "uma_name": "Matikanefukukitaru",
                "card_name": "Target costume",
            }
            parent_target = {
                "card_id": 100101,
                "uma_name": "Special Week",
                "card_name": "Parent to produce",
            }
            branch_row = {
                **lineage_row,
                **preview["p1"],
                "lineage_preview": {
                    key: value
                    for key, value in preview.items()
                    if key == "p1" or key.startswith("p1-")
                },
            }
            future_row = {
                **preview["p1"],
                "score": 71.25,
                "affinity_raw": 28,
                "g1_count": 17,
                "lineage_preview": branch_row["lineage_preview"],
            }
            gp_row = {
                "score": 79.31,
                "fixed_grandparent": preview["p1"],
                "candidate": preview["p2"],
                "lineage_preview": preview,
                "final_parent_affinity": {
                    "potential_total": 168,
                    "common_g1_count": 8,
                },
            }
            fixtures = (
                ("lineage-pair", target_ace, lineage_row, "pair"),
                ("lineage-branch", target_ace, branch_row, "branch"),
                ("lineage-future-gp", parent_target, future_row, "future"),
                (
                    "lineage-grandparent-pair",
                    parent_target,
                    gp_row,
                    "online_grandparent",
                ),
            )
            embedded_profile = {
                "surface": "dirt",
                "distance": "medium",
                "style": "pace_chaser",
            }
            pair_pane = ResultPane("pair", window.context)
            pair_pane.set_rows(
                [lineage_row],
                embedded_profile,
                lineage_root=target_ace,
            )
            online_row = {
                **lineage_row,
                "fixed_parent": preview["p1"],
                "candidate": {
                    **preview["p2"],
                    "online": {
                        "friend_code": "123 456 789 012",
                        "trainer_name": "Layout QA",
                    },
                },
            }
            online_pane = OnlineResultsPane(window.context)
            online_pane.set_payload(
                {
                    "ace": target_ace,
                    "metadata": {"profile": embedded_profile},
                    "results": [online_row],
                },
                "parent",
            )
            panes = (
                ("embedded-pair-results", pair_pane),
                ("embedded-online-results", online_pane),
            )
            for variant, pane in panes:
                try:
                    print(f"Auditing {language}/{variant}...", flush=True)
                    pane.show()
                    for width, height in SIZES:
                        pane.resize(width, height)
                        application.processEvents()
                        name = f"{language}-{variant}-{width}x{height}.png"
                        pane.grab().save(str(output_dir / name), "PNG")
                        issues = audit_window(pane)
                        report["screens"].append(
                            {
                                "language": language,
                                "page": variant,
                                "size": [width, height],
                                "screenshot": name,
                                "issues": issues,
                            }
                        )
                        for issue in issues:
                            report["issues"].append(
                                f"{language}/{variant}/{width}x{height}: {issue}"
                            )
                finally:
                    _dispose_widget(pane, application)
            for variant, root, row, mode in fixtures:
                dialog = None
                try:
                    print(f"Auditing {language}/{variant}...", flush=True)
                    if mode == "online_grandparent":
                        details_html = online_detail_html(row, "grandparent", language)
                    else:
                        details_html = result_detail_html(row, mode, language)
                    dialog = LineageDialog(
                        window.context,
                        root,
                        row,
                        mode=mode,
                        details_html=details_html,
                        parent=window,
                    )
                    dialog.show()
                    for width, height in SIZES:
                        dialog.resize(width, height)
                        application.processEvents()
                        name = f"{language}-{variant}-{width}x{height}.png"
                        dialog.grab().save(str(output_dir / name), "PNG")
                        issues = audit_window(dialog)
                        report["screens"].append(
                            {
                                "language": language,
                                "page": variant,
                                "size": [width, height],
                                "screenshot": name,
                                "issues": issues,
                            }
                        )
                        for issue in issues:
                            report["issues"].append(
                                f"{language}/{variant}/{width}x{height}: {issue}"
                            )
                finally:
                    if dialog is not None:
                        _dispose_widget(dialog, application)
        _dispose_widget(window, application)
        repository = getattr(context, "_image_repository", None)
        if repository is not None:
            repository.set_enabled(False)
        context.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        application.processEvents()
    report["issue_count"] = len(report["issues"])
    (output_dir / "layout-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render and audit every Qt page.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui-audit"))
    args = parser.parse_args()
    report = run_audit(args.output)
    for issue in report["issues"]:
        print(issue, flush=True)
    print(
        f"Rendered {len(report['screens'])} screens; "
        f"detected {report['issue_count']} layout issue(s).",
        flush=True,
    )
    return 1 if report["issue_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

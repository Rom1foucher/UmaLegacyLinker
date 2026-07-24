from __future__ import annotations

import sys


def _run_legacy() -> int:
    sys.argv = [argument for argument in sys.argv if argument != "--legacy"]
    from app import main as legacy_main

    result = legacy_main()
    return int(result or 0)


def main() -> int:
    if "--legacy" in sys.argv:
        return _run_legacy()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(
            "PySide6 is required for the Qt preview. "
            "Install it with: python -m pip install -r requirements-qt.txt",
            file=sys.stderr,
        )
        return 2

    from ui_qt.main_window import MainWindow
    from ui_qt.theme import application_stylesheet

    application = QApplication(sys.argv)
    application.setApplicationName("Uma Legacy Linker")
    application.setOrganizationName("UmaLegacyLinker")
    application.setStyle("Fusion")
    application.setStyleSheet(application_stylesheet())
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())


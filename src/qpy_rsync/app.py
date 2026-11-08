from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print("PySide6 is required to run qpy-rsync.", file=sys.stderr)
        raise SystemExit(2) from exc

    from qpy_rsync.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("qpy-rsync")
    app.setOrganizationName("qpy-rsync")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

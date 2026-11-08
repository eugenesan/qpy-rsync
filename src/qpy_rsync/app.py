from __future__ import annotations

import sys


def main() -> int:
    try:
        from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
    except ImportError as exc:
        print("PySide6 is required to run qpy-rsync.", file=sys.stderr)
        raise SystemExit(2) from exc

    app = QApplication(sys.argv)
    app.setApplicationName("qpy-rsync")
    app.setOrganizationName("qpy-rsync")
    window = QMainWindow()
    window.setWindowTitle("qpy-rsync")
    window.setCentralWidget(QLabel("qpy-rsync milestone 0\nCommand and profile foundations are ready."))
    window.resize(720, 420)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

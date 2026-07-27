"""Shadow entry point: launches the PyQt6 dashboard."""
import sys

# MUST be imported before QApplication is constructed — QtWebEngine initializes
# Chromium at import time, and creating a QWebEngineView (the Code tab's Monaco
# editor, gui/ide/monaco.py) under an already-built QApplication aborts the
# process. Imported here rather than in gui/ide/ so the ordering holds no matter
# which module happens to be imported first. Unused name, hence the noqa.
from PyQt6 import QtWebEngineWidgets  # noqa: F401
from PyQt6.QtWidgets import QApplication

from gui.dashboard import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

"""Shadow entry point: launches the PyQt6 dashboard."""
import sys

from PyQt6.QtWidgets import QApplication

from gui.dashboard import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

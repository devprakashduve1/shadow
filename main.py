"""Shadow entry point: launches the PyQt6 dashboard."""
import sys
import os

def check_environment():
    """Check and report environment status."""
    import importlib.util

    required_packages = {
        'PyQt6': 'PyQt6',
        'cv2': 'opencv-python',
        'mediapipe': 'mediapipe',
        'pyautogui': 'pyautogui',
        'pynput': 'pynput',
        'mss': 'mss',
        'pytesseract': 'pytesseract',
        'easyocr': 'easyocr',
        'faster_whisper': 'faster-whisper',
        'sounddevice': 'sounddevice',
        'numpy': 'numpy',
        'pandas': 'pandas',
        'yaml': 'PyYAML',
        'PIL': 'Pillow',
    }

    missing = []
    for module_name, package_name in required_packages.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(package_name)

    if missing:
        print("ERROR: Missing required packages:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nFix: Run './run.sh --install' to install dependencies")
        sys.exit(1)


# MUST be imported before QApplication is constructed — QtWebEngine initializes
# Chromium at import time, and creating a QWebEngineView (the Code tab's Monaco
# editor, gui/ide/monaco.py) under an already-built QApplication aborts the
# process. Imported here rather than in gui/ide/ so the ordering holds no matter
# which module happens to be imported first. Unused name, hence the noqa.
try:
    from PyQt6 import QtWebEngineWidgets  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    from gui.dashboard import MainWindow
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print("\nFix: Run './run.sh --install' to install dependencies")
    sys.exit(1)


def main() -> int:
    """Main entry point for Shadow application."""
    check_environment()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

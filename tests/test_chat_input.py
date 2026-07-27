import pytest

pytest.importorskip("PyQt6")

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from gui.dashboard import ChatInput


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _press(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


def test_shift_enter_inserts_newline_without_submitting(app):
    box = ChatInput()
    submitted = []
    box.submitted.connect(lambda: submitted.append(box.toPlainText()))

    box.insertPlainText("first line")
    _press(box, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    box.insertPlainText("second line")

    assert box.toPlainText() == "first line\nsecond line"
    assert submitted == []


def test_plain_enter_submits_without_modifying_text(app):
    box = ChatInput()
    submitted = []
    box.submitted.connect(lambda: submitted.append(box.toPlainText()))

    box.insertPlainText("what broke in checkout.py?")
    _press(box, Qt.Key.Key_Return)

    assert submitted == ["what broke in checkout.py?"]
    assert box.toPlainText() == "what broke in checkout.py?"  # Enter doesn't insert a newline


def test_other_keys_are_unaffected(app):
    box = ChatInput()
    submitted = []
    box.submitted.connect(lambda: submitted.append(box.toPlainText()))

    box.insertPlainText("hello")
    _press(box, Qt.Key.Key_A)

    assert submitted == []

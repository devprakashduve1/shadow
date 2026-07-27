"""The Code tab: a VS Code-style AI coding workspace over a git repository.

Kept as its own package rather than added to `gui/dashboard.py`, which is
already ~1600 lines. `IDETab` is the only thing the dashboard needs.
"""
from .tab import IDETab

__all__ = ["IDETab"]

"""Projects window.

UX principle:
- Projects are a separate surface from Chat.
- Selecting a project opens its Knowledge Base (KB) as files in `projects/<id>/kb/`.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMainWindow

from ..db import Database
from .projects_widget import ProjectsWidget


class ProjectsWindow(QMainWindow):
    """Standalone window for managing Projects."""

    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self.setWindowTitle("ReOS - Projects")
        self.resize(QSize(1100, 800))

        self._widget = ProjectsWidget(db=self._db)
        self.setCentralWidget(self._widget)

    def refresh(self) -> None:
        """Refresh the Projects UI."""
        self._widget.refresh()

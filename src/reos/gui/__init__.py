"""ReOS GUI entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from ..errors import record_error
from ..logging_setup import configure_logging
from .main_window import MainWindow


def _install_exception_hook() -> None:
    logger = logging.getLogger(__name__)

    def _hook(exc_type: type[BaseException], exc: BaseException, tb) -> None:  # noqa: ANN001
        logger.exception("Unhandled exception in GUI", exc_info=(exc_type, exc, tb))
        record_error(source="reos", operation="gui_unhandled", exc=exc)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def main() -> None:
    """Launch the ReOS desktop application."""
    configure_logging()
    _install_exception_hook()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

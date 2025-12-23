"""Global Qt styling for ReOS GUI.

Goal: a modern, cohesive, low-noise UI across all windows without changing UX.

We prefer a single application-level stylesheet so widgets stay consistent.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication


APP_QSS = """
/* Base */
QMainWindow {
    background: #f6f7f9;
}

QWidget {
    color: #111827;
    font-size: 13px;
}

QLabel[reosMuted="true"] {
    color: #6b7280;
    font-size: 11px;
}

QLabel[reosTitle="true"] {
    font-weight: 700;
    font-size: 14px;
}

/* Inputs */
QLineEdit, QTextEdit {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 10px;
    padding: 8px;
    selection-background-color: #2b6cb0;
    selection-color: #ffffff;
}

QTextEdit {
    padding: 10px;
}

/* Lists / Trees */
QListWidget, QTreeWidget {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 12px;
}

QListWidget::item, QTreeWidget::item {
    padding: 6px;
    border-radius: 8px;
}

QListWidget::item:selected, QTreeWidget::item:selected {
    background: #2b6cb0;
    color: #ffffff;
}

/* Buttons */
QPushButton {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 10px;
    padding: 7px 12px;
}

QPushButton:hover {
    background: #f9fafb;
}

QPushButton:pressed {
    background: #f3f4f6;
}

QPushButton:disabled {
    color: #9ca3af;
    border-color: #e5e7eb;
    background: #f9fafb;
}

/* Splitters */
QSplitter::handle {
    background: transparent;
}

QSplitter::handle:hover {
    background: #e5e7eb;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #d1d5db;
    border-radius: 12px;
    background: #ffffff;
    top: -1px;
}

QTabBar::tab {
    background: #f3f4f6;
    border: 1px solid #d1d5db;
    border-bottom: none;
    padding: 8px 12px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}

QTabBar::tab:selected {
    background: #ffffff;
}

/* Chat bubbles (property-driven) */
QFrame[reosChatBubble="true"] {
    border-radius: 14px;
}

QFrame[reosChatBubble="true"][reosRole="user"] {
    background: #2b6cb0;
}

QFrame[reosChatBubble="true"][reosRole="reos"] {
    background: #dd6b20;
}

QFrame[reosChatBubble="true"] QLabel {
    color: #ffffff;
}

/* Pane framing */
#reosNavPane, #reosInspectionPane {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}
"""


def apply_global_style(app: QApplication) -> None:
    """Apply the ReOS global stylesheet."""

    # Fusion generally looks cleaner and more consistent cross-platform.
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    app.setStyleSheet(APP_QSS)

"""Main window: 3-pane layout (nav | chat | inspection)."""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..errors import record_error
from ..git_poll import poll_git_repo
from ..logging_setup import configure_logging

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """ReOS desktop app: transparent AI reasoning in a 1080p window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ReOS - Attention Kernel")
        self.resize(QSize(1920, 1080))  # 1080p-ish (width for 3 panes)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # Left pane: Navigation
        left_pane = self._create_nav_pane()

        # Center pane: Chat
        center_pane = self._create_chat_pane()

        # Right pane: Inspection
        right_pane = self._create_inspection_pane()

        # Use splitters for resizable panes
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.addWidget(left_pane)
        main_split.addWidget(center_pane)
        main_split.addWidget(right_pane)

        # Default proportions: nav (15%), chat (50%), inspection (35%)
        main_split.setSizes([288, 960, 672])
        layout.addWidget(main_split)

        self._last_review_trigger_id: str | None = None
        self._last_alignment_trigger_id: str | None = None

        # Refresh every 30 seconds to poll git + show repo status
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_nav_pane)
        self.refresh_timer.start(30000)  # 30 second refresh

    def _create_nav_pane(self) -> QWidget:
        """Left navigation pane: shows git repo status and checkpoint signals."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("Git Repo")
        title.setStyleSheet(
            "font-weight: bold; font-size: 14px;"
        )
        layout.addWidget(title)

        # Session summary from SQLite
        self.nav_list = QListWidget()
        self.nav_list.itemClicked.connect(self._on_nav_item_clicked)
        layout.addWidget(self.nav_list)
        
        # Refresh nav pane with current session data
        self._refresh_nav_pane()

        layout.addStretch()
        return widget
    
    def _refresh_nav_pane(self) -> None:
        """Refresh navigation pane with current git repo data."""
        try:
            configure_logging()
            db = Database()
            repo_summary = poll_git_repo()
            
            # Clear current list
            self.nav_list.clear()

            status_text = repo_summary.get("status", "no_repo_detected")
            if status_text != "ok":
                item = QListWidgetItem("No git repo detected (set REOS_REPO_PATH)")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.nav_list.addItem(item)
                self._check_review_trigger(db)
                return

            repo = repo_summary.get("repo", "")
            branch = repo_summary.get("branch")
            changed_files_count = repo_summary.get("changed_files_count", 0)

            repo_item = QListWidgetItem(f"Repo: {repo}")
            repo_item.setFlags(repo_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.addItem(repo_item)

            branch_text = branch if branch else "(detached)"
            branch_item = QListWidgetItem(f"Branch: {branch_text}")
            branch_item.setFlags(branch_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.addItem(branch_item)

            changes_item = QListWidgetItem(f"Working tree: {changed_files_count} changed files")
            changes_item.setFlags(changes_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.addItem(changes_item)

            diff_stat = repo_summary.get("diff_stat")
            if isinstance(diff_stat, str) and diff_stat:
                stat_item = QListWidgetItem("Diffstat: " + diff_stat.replace("\n", " | "))
                stat_item.setFlags(stat_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.nav_list.addItem(stat_item)

            self._check_review_trigger(db)
                
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to refresh nav pane")
            record_error(source="reos", operation="gui_refresh_nav_pane", exc=exc)
            item = QListWidgetItem(f"Error loading repo: {exc}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.clear()
            self.nav_list.addItem(item)

    def _check_review_trigger(self, db: Database) -> None:
        """If a new review-trigger event exists, append a checkpoint prompt."""
        for evt in db.iter_events_recent(limit=50):
            if evt.get("kind") != "review_trigger":
                continue
            evt_id = evt.get("id")
            if isinstance(evt_id, str) and evt_id == self._last_review_trigger_id:
                return

            self._last_review_trigger_id = str(evt_id) if evt_id else None

            utilization = None
            try:
                import json

                payload_raw = evt.get("payload_metadata")
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}
                utilization = payload.get("utilization")
            except Exception:
                utilization = None

            util_text = "" if not isinstance(utilization, int | float) else f" ({utilization:.0%})"
            msg = (
                "Your current changes + roadmap/charter may be nearing the review context budget"
                f"{util_text}.\n"
                "Want to checkpoint with `review_alignment` before the thread gets too large?"
            )
            self.chat_display.append(f"\nReOS: {msg}")
            return

        for evt in db.iter_events_recent(limit=50):
            if evt.get("kind") != "alignment_trigger":
                continue
            evt_id = evt.get("id")
            if isinstance(evt_id, str) and evt_id == self._last_alignment_trigger_id:
                return

            self._last_alignment_trigger_id = str(evt_id) if evt_id else None

            msg = (
                "Quick checkpoint: your current changes may be opening multiple threads "
                "or drifting from the roadmap/charter.\n"
                "Want to run `review_alignment` to compare changes against the "
                "tech roadmap + charter?"
            )
            self.chat_display.append(f"\nReOS: {msg}")
            return

    def _on_nav_item_clicked(self, item: QListWidgetItem) -> None:
        """Handle navigation item click: load project context."""
        project_name = item.data(Qt.ItemDataRole.UserRole)
        if not project_name:
            return
        
        # In center pane, show: "Loaded project: {project_name}"
        # This is a placeholder for future implementation
        msg = f"Project context for: {project_name}\n(Project inspection coming next)"
        self.chat_display.append(f"\nReOS: {msg}")


    def _create_chat_pane(self) -> QWidget:
        """Center chat pane."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Chat history display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        initial_msg = (
            "ReOS: Hello! I'm here to help you understand your "
            "attention patterns.\n\nTell me about your work."
        )
        self.chat_display.setText(initial_msg)
        layout.addWidget(self.chat_display, stretch=1)

        # Input area
        input_label = QLabel("You:")
        input_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(input_label)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.returnPressed.connect(self._on_send_message)
        layout.addWidget(self.chat_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._on_send_message)
        layout.addWidget(send_btn)

        return widget

    def _create_inspection_pane(self) -> QWidget:
        """Right inspection pane: click on AI responses to see reasoning."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("Inspection Pane")
        title.setStyleSheet(
            "font-weight: bold; font-size: 14px;"
        )
        layout.addWidget(title)

        info = QLabel(
            "(Click on an AI message in the chat to inspect "
            "its reasoning trail)"
        )
        info.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(info)

        self.inspection_display = QTextEdit()
        self.inspection_display.setReadOnly(True)
        default_text = (
            "No message selected.\n\nInspection details will "
            "appear here."
        )
        self.inspection_display.setText(default_text)
        layout.addWidget(self.inspection_display, stretch=1)

        return widget

    def _on_send_message(self) -> None:
        """Handle user message (placeholder for now)."""
        text = self.chat_input.text().strip()
        if not text:
            return

        # Append to chat
        self.chat_display.append(f"\nYou: {text}")
        self.chat_input.clear()

        # Placeholder response
        response = (
            "\nReOS: I received your message. "
            "(Command interpreter and Ollama integration coming next.)"
        )
        self.chat_display.append(response)

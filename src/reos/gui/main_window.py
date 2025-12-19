"""Main window: 3-pane layout (nav | chat | inspection)."""

from __future__ import annotations

import logging

import json
from dataclasses import asdict, is_dataclass

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..agent import ChatAgent
from ..commit_watch import poll_commits_and_review
from ..db import Database, get_db
from ..errors import record_error
from ..git_poll import poll_git_repo
from ..logging_setup import configure_logging
from .projects_window import ProjectsWindow
from .settings_window import SettingsWindow

logger = logging.getLogger(__name__)


class _ChatAgentThread(QThread):
    def __init__(self, *, agent: ChatAgent, user_text: str) -> None:
        super().__init__()
        self._agent = agent
        self._user_text = user_text
        self.answer: str | None = None
        self.trace: object | None = None
        self.error: str | None = None

    def run(self) -> None:  # noqa: D401
        try:
            answer, trace = self._agent.respond(self._user_text)
            self.answer = answer
            self.trace = trace
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)


class _CommitReviewThread(QThread):
    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self.new_reviews: list[dict[str, object]] = []
        self.error: str | None = None

    def run(self) -> None:  # noqa: D401
        try:
            reviews = poll_commits_and_review(db=self._db)
            self.new_reviews = [
                {
                    "event_id": r.event_id,
                    "project_id": r.project_id,
                    "repo_id": r.repo_id,
                    "repo_path": r.repo_path,
                    "commit_sha": r.commit_sha,
                    "subject": r.subject,
                    "review_text": r.review_text,
                }
                for r in reviews
            ]
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)


class MainWindow(QMainWindow):
    """ReOS desktop app: transparent AI reasoning in a 1080p window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ReOS - Attention Kernel")
        self.resize(QSize(1920, 1080))  # 1080p-ish (width for 3 panes)

        self._db = get_db()
        self._agent = ChatAgent(db=self._db)
        self._projects_window: ProjectsWindow | None = None
        self._settings_window: SettingsWindow | None = None
        self._chat_thread: _ChatAgentThread | None = None
        self._commit_thread: _CommitReviewThread | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        # Left pane: Navigation
        left_pane = self._create_nav_pane()

        # Center pane: Chat (always)
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
        self._last_commit_review_id: str | None = None

        # Refresh every 30 seconds to poll git + emit checkpoint prompts in chat
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_nav_pane)
        self.refresh_timer.start(30000)  # 30 second refresh

    def _create_nav_pane(self) -> QWidget:
        """Left navigation pane."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("Navigation")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        projects_btn = QPushButton("Projects")
        projects_btn.clicked.connect(self._open_projects_window)
        layout.addWidget(projects_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings_window)
        layout.addWidget(settings_btn)

        layout.addStretch()
        return widget

    def _open_projects_window(self) -> None:
        if self._projects_window is None:
            self._projects_window = ProjectsWindow(db=self._db)

        self._projects_window.refresh()
        self._projects_window.show()
        self._projects_window.raise_()
        self._projects_window.activateWindow()

    def _open_settings_window(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(db=self._db)

        self._settings_window.refresh()
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()
    
    def _refresh_nav_pane(self) -> None:
        """Poll git + emit checkpoint prompts in the chat."""
        try:
            configure_logging()
            db = self._db
            repo_summary = poll_git_repo()

            # Commit reviews can be slow (LLM). Run them in a background thread.
            if self._commit_thread is None or not self._commit_thread.isRunning():
                self._commit_thread = _CommitReviewThread(db=db)
                self._commit_thread.finished.connect(self._on_commit_review_finished)
                self._commit_thread.start()

            status_text = repo_summary.get("status", "no_repo_detected")
            if status_text != "ok":
                self._check_review_trigger(db)
                return

            self._check_review_trigger(db)
                
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to refresh nav pane")
            record_error(source="reos", operation="gui_refresh_nav_pane", exc=exc)
            self.chat_display.append(f"\nReOS: Error during refresh: {exc}")

    def _on_commit_review_finished(self) -> None:
        if self._commit_thread is None:
            return

        if self._commit_thread.error:
            self.chat_display.append(
                f"\nReOS: Commit review error: {self._commit_thread.error}"
            )
            return

        for r in self._commit_thread.new_reviews:
            event_id = r.get("event_id")
            if isinstance(event_id, str) and event_id == self._last_commit_review_id:
                continue
            if isinstance(event_id, str):
                self._last_commit_review_id = event_id

            sha = r.get("commit_sha")
            subject = r.get("subject")
            review_text = r.get("review_text")
            sha_short = sha[:10] if isinstance(sha, str) and len(sha) >= 10 else (sha or "")

            headline = (
                f"New commit review ({sha_short}): {subject}"
                if isinstance(subject, str) and subject
                else f"New commit review ({sha_short})"
            )

            body = review_text if isinstance(review_text, str) and review_text else "(no review text)"
            self.chat_display.append(f"\nReOS: {headline}\n\n{body}")

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
        """Handle user message."""
        text = self.chat_input.text().strip()
        if not text:
            return

        # Append to chat
        self.chat_display.append(f"\nYou: {text}")
        self.chat_input.clear()

        if self._chat_thread is not None and self._chat_thread.isRunning():
            self.chat_display.append("\nReOS: One moment — still thinking on the last message.")
            return

        self.chat_display.append("\nReOS: (thinking…)")
        self.inspection_display.setText("Running local tools (metadata-first)…")

        thread = _ChatAgentThread(agent=self._agent, user_text=text)
        thread.finished.connect(self._on_agent_finished)
        self._chat_thread = thread
        thread.start()

    def _on_agent_finished(self) -> None:
        thread = self._chat_thread
        self._chat_thread = None
        if thread is None:
            return

        if thread.error:
            msg = thread.error
            if "Ollama" in msg or "11434" in msg:
                msg = (
                    msg
                    + "\n\nHint: start Ollama and set REOS_OLLAMA_MODEL, e.g. `export REOS_OLLAMA_MODEL=llama3.2`."
                )
            self.chat_display.append(f"\nReOS: {msg}")
            self.inspection_display.setText(msg)
            return

        answer = thread.answer or "(no response)"
        self.chat_display.append(f"\nReOS: {answer}")

        trace = thread.trace
        try:
            payload: object
            if is_dataclass(trace):
                payload = asdict(trace)
            else:
                payload = {
                    "tool_calls": getattr(trace, "tool_calls", None),
                    "tool_results": getattr(trace, "tool_results", None),
                }

            trace_json = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        except Exception:
            trace_json = str(trace)
        self.inspection_display.setText(trace_json)

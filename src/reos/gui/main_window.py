"""Main window: 3-pane layout (nav | chat | inspection)."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from dataclasses import asdict, is_dataclass

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
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
        self._typing_timer: QTimer | None = None
        self._typing_step: int = 0
        self._typing_row: QWidget | None = None
        self._typing_label: QLabel | None = None
        self._bubble_max_width_ratio: float = 0.78
        self._last_assistant_text: str | None = None

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
        widget.setObjectName("reosNavPane")
        layout = QVBoxLayout(widget)

        title = QLabel("Navigation")
        title.setProperty("reosTitle", True)
        layout.addWidget(title)

        projects_btn = QPushButton("Projects")
        projects_btn.clicked.connect(self._open_projects_window)
        layout.addWidget(projects_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._open_settings_window)
        layout.addWidget(settings_btn)

        layout.addStretch()
        return widget

    def _append_chat(self, *, role: str, text: str) -> None:
        if not hasattr(self, "_chat_layout"):
            return

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = QFrame()
        bubble.setFrameShape(QFrame.Shape.NoFrame)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setProperty("reosChatBubble", True)
        bubble.setProperty("reosRole", "user" if role == "user" else "reos")

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(0)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(label)

        if role == "user":
            row_layout.addStretch(1)
            row_layout.addWidget(bubble)
        else:
            row_layout.addWidget(bubble)
            row_layout.addStretch(1)

        # Insert above the stretch spacer.
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)
        self._refresh_bubble_widths()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

    def _refresh_bubble_widths(self) -> None:
        if not hasattr(self, "_chat_scroll"):
            return
        viewport_width = self._chat_scroll.viewport().width()
        if viewport_width <= 0:
            return

        # Chat layout has left/right margins of 12px each; keep a little slack.
        available = max(0, viewport_width - 24)
        max_width = int(available * self._bubble_max_width_ratio)
        if max_width <= 0:
            return

        if not hasattr(self, "_chat_container"):
            return

        for bubble in self._chat_container.findChildren(QFrame):
            if bubble.property("reosChatBubble") is True:
                bubble.setMaximumWidth(max_width)

    def _scroll_chat_to_bottom(self) -> None:
        if not hasattr(self, "_chat_scroll"):
            return
        bar = self._chat_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _start_typing_indicator(self) -> None:
        self._stop_typing_indicator()

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        bubble = QFrame()
        bubble.setFrameShape(QFrame.Shape.NoFrame)
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        bubble.setProperty("reosChatBubble", True)
        bubble.setProperty("reosRole", "reos")

        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(0)

        label = QLabel("…")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        bubble_layout.addWidget(label)

        row_layout.addWidget(bubble)
        row_layout.addStretch(1)

        self._typing_row = row
        self._typing_label = label
        self._typing_step = 0
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, row)
        self._refresh_bubble_widths()
        QTimer.singleShot(0, self._scroll_chat_to_bottom)

        timer = QTimer(self)
        timer.timeout.connect(self._advance_typing_indicator)
        timer.start(350)
        self._typing_timer = timer

    def _advance_typing_indicator(self) -> None:
        if self._typing_label is None:
            return
        self._typing_step = (self._typing_step + 1) % 4
        dots = "." * self._typing_step
        self._typing_label.setText(dots if dots else "…")

    def _stop_typing_indicator(self) -> None:
        if self._typing_timer is not None:
            self._typing_timer.stop()
            self._typing_timer.deleteLater()
            self._typing_timer = None

        if self._typing_row is not None:
            self._typing_row.setParent(None)
            self._typing_row.deleteLater()
            self._typing_row = None
            self._typing_label = None

    def eventFilter(self, obj: object, event: object) -> bool:  # noqa: N802
        if hasattr(self, "_chat_scroll") and obj is self._chat_scroll.viewport():
            if isinstance(event, QEvent) and event.type() == QEvent.Type.Resize:
                self._refresh_bubble_widths()
        return super().eventFilter(obj, event)

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
            self._append_chat(role="reos", text=f"Error during refresh: {exc}")

    def _on_commit_review_finished(self) -> None:
        if self._commit_thread is None:
            return

        if self._commit_thread.error:
            self._append_chat(role="reos", text=f"Commit review error: {self._commit_thread.error}")
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

            body = (
                review_text
                if isinstance(review_text, str) and review_text
                else "(no review text)"
            )
            self._append_chat(role="reos", text=f"{headline}\n\n{body}")

    def _check_review_trigger(self, db: Database) -> None:
        """If a new review-trigger event exists, append a checkpoint prompt."""
        for evt in db.iter_events_recent(limit=50):
            if evt.get("kind") != "alignment_trigger":
                continue
            evt_id = evt.get("id")
            if isinstance(evt_id, str) and evt_id == self._last_alignment_trigger_id:
                return

            self._last_alignment_trigger_id = str(evt_id) if evt_id else None

            project_id = None
            repo_path = None
            roadmap_path = None
            charter_path = None
            unmapped_count = None
            changed_file_count = None
            area_count = None
            unmapped_examples: list[str] = []

            try:
                import json

                payload_raw = evt.get("payload_metadata")
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else {}

                project_id = payload.get("project_id")
                repo_path = payload.get("repo")
                roadmap_path = (payload.get("roadmap") or {}).get("path") if isinstance(payload.get("roadmap"), dict) else None
                charter_path = (payload.get("charter") or {}).get("path") if isinstance(payload.get("charter"), dict) else None

                signals = payload.get("signals") if isinstance(payload.get("signals"), dict) else {}
                unmapped_count = signals.get("unmapped_changed_files_count")
                changed_file_count = signals.get("changed_file_count")
                area_count = signals.get("area_count")

                examples = payload.get("examples") if isinstance(payload.get("examples"), dict) else {}
                unmapped_examples = examples.get("unmapped_changed_files") if isinstance(examples.get("unmapped_changed_files"), list) else []
            except Exception:
                pass

            who = f"Project: {project_id}" if isinstance(project_id, str) and project_id else "Project: (not set)"
            where = f"Repo: {repo_path}" if isinstance(repo_path, str) and repo_path else "Repo: (unknown)"
            against = []
            if isinstance(roadmap_path, str) and roadmap_path:
                against.append(f"Roadmap: {roadmap_path}")
            if isinstance(charter_path, str) and charter_path:
                against.append(f"Charter: {charter_path}")
            against_text = "\n".join(against) if against else "Roadmap/Charter: (not recorded)"

            sig_bits: list[str] = []
            if isinstance(unmapped_count, int | float):
                sig_bits.append(f"unmapped files: {int(unmapped_count)}")
            if isinstance(changed_file_count, int | float):
                sig_bits.append(f"changed files: {int(changed_file_count)}")
            if isinstance(area_count, int | float):
                sig_bits.append(f"areas: {int(area_count)}")
            sig_line = ", ".join(sig_bits) if sig_bits else "(no signal summary available)"

            examples_line = ""
            if unmapped_examples:
                sample = ", ".join(str(x) for x in unmapped_examples[:5])
                examples_line = f"\nExamples (unmapped): {sample}"

            msg = (
                "Quick checkpoint (metadata-only):\n"
                f"{who}\n"
                f"{where}\n"
                f"{against_text}\n"
                f"Signals: {sig_line}{examples_line}\n\n"
                "Want to run `review_alignment` for the full report?"
            )
            self._append_chat(role="reos", text=msg)
            return

    def _create_chat_pane(self) -> QWidget:
        """Center chat pane."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Chat history display (bubble list)
        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._chat_scroll.viewport().installEventFilter(self)

        self._chat_container = QWidget()
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(12, 12, 12, 12)
        self._chat_layout.setSpacing(10)
        self._chat_layout.addStretch(1)
        self._chat_scroll.setWidget(self._chat_container)
        layout.addWidget(self._chat_scroll, stretch=1)

        self._append_chat(
            role="reos",
            text=(
                "Hello! I'm here to help you understand your attention patterns.\n\n"
                "Tell me about your work."
            ),
        )

        # Input area
        input_label = QLabel("You:")
        input_label.setProperty("reosTitle", True)
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
        widget.setObjectName("reosInspectionPane")
        layout = QVBoxLayout(widget)

        title = QLabel("Inspection Pane")
        title.setProperty("reosTitle", True)
        layout.addWidget(title)

        info = QLabel(
            "(Click on an AI message in the chat to inspect "
            "its reasoning trail)"
        )
        info.setProperty("reosMuted", True)
        layout.addWidget(info)

        self.inspection_display = QTextEdit()
        self.inspection_display.setReadOnly(True)
        default_text = (
            "No message selected.\n\nInspection details will "
            "appear here."
        )
        self.inspection_display.setText(default_text)
        layout.addWidget(self.inspection_display, stretch=1)

        self.apply_patch_btn = QPushButton("Preview/Apply Patch")
        self.apply_patch_btn.setEnabled(False)
        self.apply_patch_btn.clicked.connect(self._on_preview_apply_patch)
        layout.addWidget(self.apply_patch_btn)

        return widget

    def _on_send_message(self) -> None:
        """Handle user message."""
        text = self.chat_input.text().strip()
        if not text:
            return

        self._append_chat(role="user", text=text)
        self.chat_input.clear()

        if self._chat_thread is not None and self._chat_thread.isRunning():
            self._append_chat(role="reos", text="One moment — still thinking on the last message.")
            return

        self._start_typing_indicator()
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

        self._stop_typing_indicator()

        if thread.error:
            msg = thread.error
            if "Ollama" in msg or "11434" in msg:
                msg = (
                    msg
                    + "\n\nHint: start Ollama and set REOS_OLLAMA_MODEL, e.g. "
                    "`export REOS_OLLAMA_MODEL=llama3.2`."
                )
            self._append_chat(role="reos", text=msg)
            self.inspection_display.setText(msg)
            return

        answer = thread.answer or "(no response)"
        self._append_chat(role="reos", text=answer)
        self._last_assistant_text = answer
        self.apply_patch_btn.setEnabled(bool(self._extract_unified_diff(answer)))

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

    def _extract_unified_diff(self, text: str) -> str | None:
        """Extract a unified diff from assistant text.

        Supports:
        - fenced codeblocks: ```diff ... ```
        - raw patches starting with 'diff --git'
        """

        if not text.strip():
            return None

        fence = re.search(r"```(?:diff|patch)\n(.*?)\n```", text, flags=re.DOTALL | re.IGNORECASE)
        if fence:
            payload = fence.group(1).strip("\n")
            return payload or None

        raw = re.search(r"(diff --git[\s\S]+)", text)
        if raw:
            payload = raw.group(1).strip("\n")
            return payload or None

        return None

    def _patch_targets_are_kb_only(self, patch_text: str) -> bool:
        """Return True iff all changed paths are under projects/<id>/kb/."""

        # Extract paths from +++/--- lines; accept both a/ and b/ prefixes.
        paths: set[str] = set()
        for line in patch_text.splitlines():
            if line.startswith("+++ ") or line.startswith("--- "):
                _, p = line.split(" ", 1)
                p = p.strip()
                if p in {"/dev/null"}:
                    continue
                if p.startswith("a/") or p.startswith("b/"):
                    p = p[2:]
                paths.add(p)

        if not paths:
            # If we can't determine targets safely, deny.
            return False

        for p in paths:
            if not p.startswith("projects/"):
                return False
            if "/kb/" not in p:
                return False
        return True

    def _on_preview_apply_patch(self) -> None:
        patch = self._extract_unified_diff(self._last_assistant_text or "")
        if not patch:
            return

        if not self._patch_targets_are_kb_only(patch):
            self._append_chat(
                role="reos",
                text=(
                    "I found a patch, but it targets files outside `projects/<id>/kb/`, "
                    "so I won't apply it automatically."
                ),
            )
            return

        # Preview in a dialog and apply via `git apply` only on explicit confirmation.
        from PySide6.QtWidgets import QDialog  # local import to avoid GUI cycles

        dlg = QDialog(self)
        dlg.setWindowTitle("Preview/Apply Patch")
        root = QVBoxLayout(dlg)

        info = QLabel("This will apply the patch to your ReOS workspace (ready to commit).")
        info.setStyleSheet("color: #666; font-size: 11px;")
        root.addWidget(info)

        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(patch)
        box.setMinimumSize(900, 520)
        root.addWidget(box, stretch=1)

        buttons = QHBoxLayout()
        root.addLayout(buttons)
        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        buttons.addWidget(cancel)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(dlg.accept)
        buttons.addWidget(apply_btn)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        repo_root = Path(__file__).resolve().parents[3]
        try:
            check = subprocess.run(
                ["git", "apply", "--check", "-"],
                input=patch,
                text=True,
                cwd=repo_root,
                capture_output=True,
                check=False,
            )
            if check.returncode != 0:
                self._append_chat(role="reos", text=f"Patch check failed:\n{check.stderr or check.stdout}")
                return

            res = subprocess.run(
                ["git", "apply", "-"],
                input=patch,
                text=True,
                cwd=repo_root,
                capture_output=True,
                check=False,
            )
            if res.returncode != 0:
                self._append_chat(role="reos", text=f"Patch apply failed:\n{res.stderr or res.stdout}")
                return

        except Exception as exc:  # noqa: BLE001
            self._append_chat(role="reos", text=f"Patch apply error: {exc}")
            return

        self._append_chat(role="reos", text="Patch applied to KB files (ready to commit).")

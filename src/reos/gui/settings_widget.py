"""Settings UI.

Two sections:
- Ollama (server URL, test, model selection, save)
- Agent Personas (system prompt + default context + tuning knobs; save and set active)
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..ollama import check_ollama, list_ollama_models


_DEFAULT_PERSONA_ID = "persona-default"


def _default_system_prompt() -> str:
    return (
        "You are ReOS, a local-first companion for a developer.\n"
        "Purpose: protect, reflect, and return human attention.\n\n"
        "Rules:\n"
        "- Be descriptive and compassionate; avoid moral judgment.\n"
        "- Prefer metadata-first signals (project charter + git summary).\n"
        "- Treat the project_charter as human-authored ground truth; never invent or edit it.\n"
        "- Only request diffs when the user explicitly opts in.\n"
        "- When you cite the charter, cite the field names (e.g., core_intent, definition_of_done).\n"
    )


def _default_context() -> str:
    return (
        "Default persona context:\n"
        "- Local-only reasoning (Ollama).\n"
        "- Repo-scoped tools (active project).\n"
        "- Transparency: show a tool trace in the inspection pane.\n"
    )


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class SettingsWidget(QWidget):
    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db
        self._selected_persona_id: str | None = None

        root = QVBoxLayout(self)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        self._ollama_tab = QWidget()
        self._personas_tab = QWidget()
        self.tabs.addTab(self._ollama_tab, "Ollama")
        self.tabs.addTab(self._personas_tab, "Agent Personas")

        self._build_ollama_tab(self._ollama_tab)
        self._build_personas_tab(self._personas_tab)

        self.status = QLabel("")
        self.status.setProperty("reosMuted", True)
        root.addWidget(self.status)

        self.refresh()

    def refresh(self) -> None:
        self._ensure_default_persona()
        self._load_ollama_settings()
        self._load_personas()

    # --- Ollama tab ---

    def _build_ollama_tab(self, tab: QWidget) -> None:
        layout = QVBoxLayout(tab)

        header = QLabel("Ollama")
        header.setProperty("reosTitle", True)
        layout.addWidget(header)

        form = QFormLayout()
        layout.addLayout(form)

        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        form.addRow("Server URL", self.ollama_url)

        self.ollama_models = QComboBox()
        form.addRow("Model", self.ollama_models)

        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)

        self.ollama_test_btn = QPushButton("Test connection")
        self.ollama_test_btn.clicked.connect(self._on_ollama_test)
        btn_row.addWidget(self.ollama_test_btn)

        self.ollama_refresh_models_btn = QPushButton("Refresh models")
        self.ollama_refresh_models_btn.clicked.connect(self._on_ollama_refresh_models)
        btn_row.addWidget(self.ollama_refresh_models_btn)

        btn_row.addStretch()

        self.ollama_save_btn = QPushButton("Save")
        self.ollama_save_btn.clicked.connect(self._on_ollama_save)
        btn_row.addWidget(self.ollama_save_btn)

        self.ollama_status = QLabel("")
        self.ollama_status.setProperty("reosMuted", True)
        layout.addWidget(self.ollama_status)

        layout.addStretch()

    def _load_ollama_settings(self) -> None:
        url = self._db.get_state(key="ollama_url")
        model = self._db.get_state(key="ollama_model")

        if isinstance(url, str) and url:
            self.ollama_url.setText(url)
        else:
            self.ollama_url.setText("")

        self._populate_models(url=url, selected=model)

    def _populate_models(self, *, url: str | None, selected: str | None) -> None:
        self.ollama_models.clear()
        if not url:
            self.ollama_models.addItem("(enter server URL and refresh)", None)
            return

        try:
            models = list_ollama_models(url=url)
        except Exception:
            self.ollama_models.addItem("(unable to list models)", None)
            return

        if not models:
            self.ollama_models.addItem("(no models found)", None)
            return

        selected_idx = 0
        for idx, name in enumerate(models):
            self.ollama_models.addItem(name, name)
            if selected and name == selected:
                selected_idx = idx

        self.ollama_models.setCurrentIndex(selected_idx)

    def _on_ollama_test(self) -> None:
        url = self.ollama_url.text().strip()
        if not url:
            self.ollama_status.setText("Enter a server URL first.")
            return

        health = check_ollama(timeout_seconds=2.0, url=url)
        if health.reachable:
            count = health.model_count
            self.ollama_status.setText(f"Connected. Models: {count if count is not None else 'unknown'}")

            # Tiny UX touch: successful test also refreshes the model list.
            current_selected = self.ollama_models.currentData()
            selected = current_selected if isinstance(current_selected, str) and current_selected else None
            if selected is None:
                selected = self._db.get_state(key="ollama_model")
            self._populate_models(url=url, selected=selected)
        else:
            self.ollama_status.setText(f"Not reachable: {health.error}")

    def _on_ollama_refresh_models(self) -> None:
        url = self.ollama_url.text().strip()
        model = self._db.get_state(key="ollama_model")
        self._populate_models(url=url, selected=model)

    def _on_ollama_save(self) -> None:
        url = self.ollama_url.text().strip()
        model = self.ollama_models.currentData()

        if not url:
            self.ollama_status.setText("Server URL is required.")
            return

        if not isinstance(model, str) or not model:
            # Allow saving URL even if models aren't loaded.
            model = None

        self._db.set_state(key="ollama_url", value=url)
        self._db.set_state(key="ollama_model", value=model)
        self.ollama_status.setText("Saved.")

    # --- Personas tab ---

    def _build_personas_tab(self, tab: QWidget) -> None:
        layout = QHBoxLayout(tab)

        # Left list
        left = QVBoxLayout()
        layout.addLayout(left, stretch=1)

        header = QLabel("Personas")
        header.setProperty("reosTitle", True)
        left.addWidget(header)

        self.persona_list = QListWidget()
        self.persona_list.itemClicked.connect(self._on_persona_clicked)
        left.addWidget(self.persona_list, stretch=1)

        btn_row = QHBoxLayout()
        left.addLayout(btn_row)

        self.persona_new_btn = QPushButton("New")
        self.persona_new_btn.clicked.connect(self._on_persona_new)
        btn_row.addWidget(self.persona_new_btn)

        self.persona_set_active_btn = QPushButton("Set active")
        self.persona_set_active_btn.clicked.connect(self._on_persona_set_active)
        btn_row.addWidget(self.persona_set_active_btn)

        btn_row.addStretch()

        # Right editor
        right = QVBoxLayout()
        layout.addLayout(right, stretch=2)

        self.active_persona_label = QLabel("Active persona: —")
        self.active_persona_label.setProperty("reosMuted", True)
        right.addWidget(self.active_persona_label)

        form = QFormLayout()
        right.addLayout(form)

        self.persona_name = QLineEdit()
        form.addRow("Name", self.persona_name)

        self.persona_system_prompt = QTextEdit()
        self.persona_system_prompt.setMinimumHeight(140)
        form.addRow("System prompt", self.persona_system_prompt)

        self.persona_default_context = QTextEdit()
        self.persona_default_context.setMinimumHeight(110)
        form.addRow("Default context", self.persona_default_context)

        # Knobs
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setMinimum(0)
        self.temp_slider.setMaximum(100)
        self.temp_slider.valueChanged.connect(self._on_knob_changed)
        form.addRow("Temperature", self.temp_slider)

        self.temp_help = QLabel("")
        self.temp_help.setStyleSheet("color: #666; font-size: 11px;")
        right.addWidget(self.temp_help)

        self.top_p_slider = QSlider(Qt.Orientation.Horizontal)
        self.top_p_slider.setMinimum(0)
        self.top_p_slider.setMaximum(100)
        self.top_p_slider.valueChanged.connect(self._on_knob_changed)
        form.addRow("Top-p", self.top_p_slider)

        self.top_p_help = QLabel("")
        self.top_p_help.setStyleSheet("color: #666; font-size: 11px;")
        right.addWidget(self.top_p_help)

        self.tool_limit_slider = QSlider(Qt.Orientation.Horizontal)
        self.tool_limit_slider.setMinimum(0)
        self.tool_limit_slider.setMaximum(6)
        self.tool_limit_slider.valueChanged.connect(self._on_knob_changed)
        form.addRow("Tool call limit", self.tool_limit_slider)

        self.tool_limit_help = QLabel("")
        self.tool_limit_help.setStyleSheet("color: #666; font-size: 11px;")
        right.addWidget(self.tool_limit_help)

        bottom = QHBoxLayout()
        right.addLayout(bottom)

        self.persona_save_btn = QPushButton("Save persona")
        self.persona_save_btn.clicked.connect(self._on_persona_save)
        bottom.addWidget(self.persona_save_btn)

        bottom.addStretch()

        self.persona_status = QLabel("")
        self.persona_status.setStyleSheet("color: #666; font-size: 11px;")
        right.addWidget(self.persona_status)

        right.addStretch()

        self._on_knob_changed()

    def _ensure_default_persona(self) -> None:
        # Create a default persona on first run so the user can view/edit it.
        existing = self._db.iter_agent_personas()
        if existing:
            return

        self._db.upsert_agent_persona(
            persona_id=_DEFAULT_PERSONA_ID,
            name="Default",
            system_prompt=_default_system_prompt(),
            default_context=_default_context(),
            temperature=0.2,
            top_p=0.9,
            tool_call_limit=3,
        )
        self._db.set_active_persona_id(persona_id=_DEFAULT_PERSONA_ID)

    def _load_personas(self) -> None:
        self.persona_list.clear()
        active_id = self._db.get_active_persona_id()

        rows = self._db.iter_agent_personas()
        for row in rows:
            persona_id = str(row.get("id"))
            name = str(row.get("name"))
            label = name
            if active_id and persona_id == active_id:
                label = f"{name} (active)"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, persona_id)
            self.persona_list.addItem(item)

        active_name = "—"
        if active_id:
            p = self._db.get_agent_persona(persona_id=active_id)
            if p is not None:
                active_name = str(p.get("name"))
        self.active_persona_label.setText(f"Active persona: {active_name}")

        if self._selected_persona_id is None and rows:
            self._select_persona(str(rows[0].get("id")))

    def _select_persona(self, persona_id: str) -> None:
        row = self._db.get_agent_persona(persona_id=persona_id)
        if row is None:
            return

        self._selected_persona_id = persona_id
        self.persona_name.setText(str(row.get("name") or ""))
        self.persona_system_prompt.setPlainText(str(row.get("system_prompt") or ""))
        self.persona_default_context.setPlainText(str(row.get("default_context") or ""))

        temp = float(row.get("temperature") or 0.2)
        top_p = float(row.get("top_p") or 0.9)
        tool_limit = int(row.get("tool_call_limit") or 3)

        self.temp_slider.setValue(int(_clamp01(temp) * 100))
        self.top_p_slider.setValue(int(_clamp01(top_p) * 100))
        self.tool_limit_slider.setValue(max(0, min(6, tool_limit)))
        self._on_knob_changed()
        self.persona_status.setText("Loaded persona.")

    def _on_persona_clicked(self, item: QListWidgetItem) -> None:
        persona_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(persona_id, str) and persona_id:
            self._select_persona(persona_id)

    def _on_persona_new(self) -> None:
        self._selected_persona_id = None
        self.persona_name.setText("")
        self.persona_system_prompt.setPlainText(_default_system_prompt())
        self.persona_default_context.setPlainText(_default_context())
        self.temp_slider.setValue(20)
        self.top_p_slider.setValue(90)
        self.tool_limit_slider.setValue(3)
        self.persona_status.setText("New persona.")

    def _on_knob_changed(self) -> None:
        t = self.temp_slider.value() / 100.0
        p = self.top_p_slider.value() / 100.0
        limit = self.tool_limit_slider.value()

        self.temp_help.setText(
            f"Temperature {t:.2f}: lower = more deterministic; higher = more exploratory."
        )
        self.top_p_help.setText(
            f"Top-p {p:.2f}: lower = narrower vocabulary; higher = more diverse phrasing."
        )
        self.tool_limit_help.setText(
            f"Tool call limit {limit}: max tool calls ReOS may execute per message."
        )

    def _on_persona_save(self) -> None:
        name = self.persona_name.text().strip()
        if not name:
            self.persona_status.setText("Name is required.")
            return

        system_prompt = self.persona_system_prompt.toPlainText().strip()
        default_context = self.persona_default_context.toPlainText().strip()

        if not system_prompt:
            self.persona_status.setText("System prompt is required.")
            return

        if not default_context:
            self.persona_status.setText("Default context is required.")
            return

        temperature = self.temp_slider.value() / 100.0
        top_p = self.top_p_slider.value() / 100.0
        tool_limit = int(self.tool_limit_slider.value())

        persona_id = self._selected_persona_id or str(uuid.uuid4())

        try:
            self._db.upsert_agent_persona(
                persona_id=persona_id,
                name=name,
                system_prompt=system_prompt,
                default_context=default_context,
                temperature=temperature,
                top_p=top_p,
                tool_call_limit=tool_limit,
            )
        except Exception as exc:  # noqa: BLE001
            self.persona_status.setText(f"Save failed: {exc}")
            return

        self._selected_persona_id = persona_id
        self.persona_status.setText("Saved.")
        self._load_personas()

    def _on_persona_set_active(self) -> None:
        if not self._selected_persona_id:
            self.persona_status.setText("Select a persona first.")
            return

        confirm = QMessageBox.question(
            self,
            "Set active persona",
            "Set this persona as active for Chat?\n\nProceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._db.set_active_persona_id(persona_id=self._selected_persona_id)
        self.persona_status.setText("Active persona set.")
        self._load_personas()

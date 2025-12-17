"""Main window: 3-pane layout (nav | chat | inspection)."""

from __future__ import annotations

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

from ..attention import get_current_session_summary
from ..db import Database


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
        
        # Refresh nav pane every 30 seconds to show current VSCode activity
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._refresh_nav_pane)
        self.refresh_timer.start(30000)  # 30 second refresh

    def _create_nav_pane(self) -> QWidget:
        """Left navigation pane: shows VSCode projects and attention metrics."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        title = QLabel("VSCode Projects")
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
        """Refresh navigation pane with current VSCode project data."""
        try:
            db = Database()
            summary = get_current_session_summary(db)
            
            # Clear current list
            self.nav_list.clear()
            
            # Show status
            status_text = summary.get("status", "no_activity")
            if status_text == "no_activity":
                item = QListWidgetItem("No active VSCode session")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.nav_list.addItem(item)
                return
            
            # Add fragmentation metric at top
            frag = summary.get("fragmentation", {})
            frag_score = frag.get("score", 0.0)
            
            frag_item = QListWidgetItem(f"Fragmentation: {frag_score:.1%}")
            frag_item.setFlags(frag_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.addItem(frag_item)
            
            # Add each project as a clickable item
            projects = summary.get("projects", [])
            
            if not projects:
                item = QListWidgetItem("No file activity yet")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.nav_list.addItem(item)
                return
            
            for project in projects:
                name = project.get("name", "unknown")
                file_count = project.get("file_count", 0)
                duration = project.get("estimated_duration_seconds", 0)
                
                file_plural = "s" if file_count != 1 else ""
                display_text = (
                    f"{name}: {file_count} file{file_plural}, {int(duration // 60)}m"
                )
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, name)  # Store project name
                self.nav_list.addItem(item)
                
        except Exception as e:
            item = QListWidgetItem(f"Error loading projects: {e}")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.nav_list.clear()
            self.nav_list.addItem(item)
    
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

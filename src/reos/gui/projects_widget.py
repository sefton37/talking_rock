"""Projects + Knowledge Base surface.

Spec:
- Projects is its own surface (not Chat).
- Projects are folders under projects/<project-id>/kb/.
- Selecting a project opens its KB as a navigable tree of markdown pages.
- Selecting a page opens it in a dedicated document editor pane.
- Nothing is written without an explicit, user-confirmed diff preview.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import Database
from ..projects_fs import (
    ensure_project_skeleton,
    extract_repo_path,
    get_project_paths,
    is_valid_project_id,
    list_project_ids,
    projects_root,
    read_text,
    workspace_root,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _OpenDoc:
    abs_path: Path
    rel_path: str
    original_text: str


class _DiffConfirmDialog(QDialog):
    def __init__(self, *, parent: QWidget, title: str, diff_text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        root = QVBoxLayout(self)

        label = QLabel("Preview (unified diff)")
        label.setStyleSheet("font-weight: 600;")
        root.addWidget(label)

        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(diff_text or "(no changes)")
        box.setMinimumSize(900, 520)
        root.addWidget(box, stretch=1)

        buttons = QHBoxLayout()
        root.addLayout(buttons)

        buttons.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.accept)
        buttons.addWidget(apply_btn)


class ProjectsWidget(QWidget):
    """Filesystem-backed Projects + KB browser/editor."""

    def __init__(self, *, db: Database) -> None:
        super().__init__()
        self._db = db

        self._selected_project_id: str | None = None
        self._open_doc: _OpenDoc | None = None

        outer = QVBoxLayout(self)

        header_row = QHBoxLayout()
        outer.addLayout(header_row)

        title = QLabel("Projects")
        title.setProperty("reosTitle", True)
        header_row.addWidget(title)

        header_row.addStretch(1)

        self._new_project_id = QLineEdit()
        self._new_project_id.setPlaceholderText("new project id (e.g. reos)")
        self._new_project_id.setMaximumWidth(260)
        header_row.addWidget(self._new_project_id)

        self._new_btn = QPushButton("Create")
        self._new_btn.clicked.connect(self._on_create_project)
        header_row.addWidget(self._new_btn)

        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, stretch=1)

        # Left: project list
        left = QWidget()
        left_layout = QVBoxLayout(left)

        self.project_list = QListWidget()
        self.project_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.project_list.itemSelectionChanged.connect(self._on_project_selected)
        left_layout.addWidget(self.project_list, stretch=1)

        split.addWidget(left)

        # Middle: KB tree
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)

        kb_label = QLabel("Knowledge Base")
        kb_label.setProperty("reosTitle", True)
        mid_layout.addWidget(kb_label)

        self.kb_tree = QTreeWidget()
        self.kb_tree.setHeaderHidden(True)
        self.kb_tree.itemClicked.connect(self._on_tree_item_clicked)
        mid_layout.addWidget(self.kb_tree, stretch=1)

        split.addWidget(mid)

        # Right: document editor
        right = QWidget()
        right_layout = QVBoxLayout(right)

        self.doc_path_label = QLabel("(no document selected)")
        self.doc_path_label.setProperty("reosMuted", True)
        right_layout.addWidget(self.doc_path_label)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText("Select a KB page to view/edit…")
        right_layout.addWidget(self.editor, stretch=1)

        actions = QHBoxLayout()
        right_layout.addLayout(actions)

        self.link_repo_btn = QPushButton("Link repoPath…")
        self.link_repo_btn.clicked.connect(self._on_link_repo)
        actions.addWidget(self.link_repo_btn)

        actions.addStretch(1)

        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self._reload_open_document)
        actions.addWidget(self.reload_btn)

        self.save_btn = QPushButton("Save (preview diff)")
        self.save_btn.clicked.connect(self._on_save_document)
        actions.addWidget(self.save_btn)

        split.addWidget(right)

        # Default sizes: list (20%), tree (25%), editor (55%)
        split.setSizes([260, 320, 720])

        self.refresh()

    def refresh(self) -> None:
        projects_root().mkdir(parents=True, exist_ok=True)

        self.project_list.clear()
        for pid in list_project_ids():
            self.project_list.addItem(pid)

        # Keep selection if possible.
        if self._selected_project_id:
            matches = self.project_list.findItems(self._selected_project_id, Qt.MatchFlag.MatchExactly)
            if matches:
                self.project_list.setCurrentItem(matches[0])

    def _on_create_project(self) -> None:
        project_id = self._new_project_id.text().strip().lower()
        if not project_id:
            QMessageBox.warning(self, "Missing project id", "Enter a project id.")
            return
        if not is_valid_project_id(project_id):
            QMessageBox.warning(
                self,
                "Invalid project id",
                "Use 2-64 chars: a-z, 0-9, '-' or '_', starting with a letter/number.",
            )
            return

        try:
            ensure_project_skeleton(project_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to create project")
            QMessageBox.critical(self, "Create failed", str(exc))
            return

        self._new_project_id.clear()
        self.refresh()
        matches = self.project_list.findItems(project_id, Qt.MatchFlag.MatchExactly)
        if matches:
            self.project_list.setCurrentItem(matches[0])

    def _on_project_selected(self) -> None:
        items = self.project_list.selectedItems()
        if not items:
            return

        project_id = items[0].text()
        self._selected_project_id = project_id
        self._db.set_active_project_id(project_id=project_id)

        # Ensure skeleton so charter/roadmap/settings exist.
        ensure_project_skeleton(project_id)

        self._populate_tree(project_id)

    def _populate_tree(self, project_id: str) -> None:
        self.kb_tree.clear()

        paths = get_project_paths(project_id)
        root_item = QTreeWidgetItem([f"{project_id}"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.kb_tree.addTopLevelItem(root_item)
        root_item.setExpanded(True)

        kb_item = QTreeWidgetItem(["kb"])
        kb_item.setData(0, Qt.ItemDataRole.UserRole, None)
        root_item.addChild(kb_item)
        kb_item.setExpanded(True)

        def add_file(parent: QTreeWidgetItem, abs_path: Path) -> None:
            rel = str(abs_path.relative_to(workspace_root()))
            it = QTreeWidgetItem([abs_path.name])
            it.setData(0, Qt.ItemDataRole.UserRole, rel)
            parent.addChild(it)

        add_file(kb_item, paths.charter_md)
        add_file(kb_item, paths.roadmap_md)
        add_file(kb_item, paths.settings_md)

        pages_item = QTreeWidgetItem(["pages"])
        pages_item.setData(0, Qt.ItemDataRole.UserRole, None)
        kb_item.addChild(pages_item)

        tables_item = QTreeWidgetItem(["tables"])
        tables_item.setData(0, Qt.ItemDataRole.UserRole, None)
        kb_item.addChild(tables_item)

        for p in sorted(paths.pages_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".md", ".markdown"}:
                add_file(pages_item, p)

        for p in sorted(paths.tables_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".md", ".csv"}:
                add_file(tables_item, p)

        pages_item.setExpanded(True)
        tables_item.setExpanded(True)

        self.kb_tree.expandAll()

    def _on_tree_item_clicked(self, item: QTreeWidgetItem) -> None:
        rel = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(rel, str) or not rel:
            return

        abs_path = (workspace_root() / rel).resolve()
        if not abs_path.exists() or not abs_path.is_file():
            QMessageBox.warning(self, "Missing file", f"File not found: {rel}")
            return

        text = read_text(abs_path)
        self._open_doc = _OpenDoc(abs_path=abs_path, rel_path=rel, original_text=text)
        self.doc_path_label.setText(rel)
        self.editor.setPlainText(text)

    def _reload_open_document(self) -> None:
        if self._open_doc is None:
            return
        if not self._open_doc.abs_path.exists():
            QMessageBox.warning(self, "Missing file", "The file no longer exists on disk.")
            return

        text = read_text(self._open_doc.abs_path)
        self._open_doc = _OpenDoc(
            abs_path=self._open_doc.abs_path,
            rel_path=self._open_doc.rel_path,
            original_text=text,
        )
        self.editor.setPlainText(text)

    def _on_save_document(self) -> None:
        if self._open_doc is None:
            QMessageBox.information(self, "No document", "Select a KB page first.")
            return

        new_text = self.editor.toPlainText()
        old_text = self._open_doc.original_text

        if new_text == old_text:
            QMessageBox.information(self, "No changes", "No changes to save.")
            return

        diff = "\n".join(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=self._open_doc.rel_path,
                tofile=self._open_doc.rel_path,
                lineterm="",
            )
        )

        dlg = _DiffConfirmDialog(
            parent=self,
            title=f"Apply changes: {self._open_doc.rel_path}",
            diff_text=diff,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            self._open_doc.abs_path.write_text(new_text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Write failed", str(exc))
            return

        # Refresh snapshot.
        self._open_doc = _OpenDoc(
            abs_path=self._open_doc.abs_path,
            rel_path=self._open_doc.rel_path,
            original_text=new_text,
        )
        QMessageBox.information(self, "Saved", "Changes written to disk (ready to commit).")

    def _on_link_repo(self) -> None:
        if self._selected_project_id is None:
            QMessageBox.information(self, "No project", "Select a project first.")
            return

        paths = get_project_paths(self._selected_project_id)
        ensure_project_skeleton(self._selected_project_id)

        repo_dir = QFileDialog.getExistingDirectory(self, "Select local repoPath")
        if not repo_dir:
            return

        settings_text = read_text(paths.settings_md) if paths.settings_md.exists() else "# Settings\n\n"
        current = extract_repo_path(settings_text)

        if current == repo_dir:
            QMessageBox.information(self, "No change", "repoPath unchanged.")
            return

        lines = settings_text.splitlines()
        out: list[str] = []
        replaced = False
        for line in lines:
            if line.strip().startswith("repoPath:"):
                out.append(f"repoPath: {repo_dir}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            if out and out[-1].strip():
                out.append("")
            out.append(f"repoPath: {repo_dir}")

        new_text = "\n".join(out) + "\n"

        diff = "\n".join(
            difflib.unified_diff(
                settings_text.splitlines(),
                new_text.splitlines(),
                fromfile=str(paths.settings_md.relative_to(workspace_root())),
                tofile=str(paths.settings_md.relative_to(workspace_root())),
                lineterm="",
            )
        )

        dlg = _DiffConfirmDialog(
            parent=self,
            title="Update settings.md (repoPath)",
            diff_text=diff,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        paths.settings_md.write_text(new_text, encoding="utf-8")

        if self._open_doc and self._open_doc.abs_path == paths.settings_md:
            self._reload_open_document()

        QMessageBox.information(self, "Updated", "repoPath saved to settings.md.")
        for field, _title, _help, required in self._VISIBLE_FIELDS:
            if field in self._line_fields:
                record[field] = self._line_fields[field].text().strip()
            else:
                record[field] = self._text_fields[field].toPlainText().strip()

            if required and not record[field]:
                return None, f"Missing required field: {field}"

        return record, None

    def _on_save(self) -> None:
        record, err = self._collect()
        if err is not None or record is None:
            self._set_status(err or "Invalid charter.")
            return

        now = _now_iso()
        if self._selected_project_id is None:
            project_id = str(uuid.uuid4())
            # On create, we must satisfy the full DB schema. Keep hidden fields
            # empty by default; users can always extend later if we add an
            # advanced editor.
            full: dict[str, str] = {
                "project_id": project_id,
                "created_at": now,
                "last_reaffirmed_at": now,
                "updated_at": now,
                "ingested_at": now,
                **record,
            }
            for field in self._ALL_DB_TEXT_FIELDS:
                if field not in full:
                    full[field] = ""
            self._db.insert_project_charter(record=full)
            self._selected_project_id = project_id
            self._set_status("Project charter created.")
        else:
            self._db.update_project_charter(project_id=self._selected_project_id, updates=record)
            self._set_status("Project charter updated.")

        self.refresh()
        if self._selected_project_id is not None:
            row = self._db.get_project_charter(project_id=self._selected_project_id)
            if row is not None:
                self.created_at_label.setText(f"Created: {row.get('created_at', '—')}")
                self.last_reaffirmed_label.setText(
                    f"Last reaffirmed: {row.get('last_reaffirmed_at', '—')}"
                )

    def _on_reaffirm(self) -> None:
        if self._selected_project_id is None:
            self._set_status("Select a project first.")
            return

        confirm = QMessageBox.question(
            self,
            "Reaffirm charter",
            (
                "Reaffirming is an explicit human confirmation that this project is still "
                "worth attention.\n\nProceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._db.reaffirm_project_charter(project_id=self._selected_project_id)
        row = self._db.get_project_charter(project_id=self._selected_project_id)
        if row is not None:
            self.last_reaffirmed_label.setText(
                f"Last reaffirmed: {row.get('last_reaffirmed_at', '—')}"
            )
        self._set_status("Charter reaffirmed.")

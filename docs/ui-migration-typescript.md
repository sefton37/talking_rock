# UI: TypeScript Desktop App (Tauri)

## Goal
Run the **desktop UI** as a **TypeScript/Tauri app**, while keeping ReOS’s core principles intact:

- Local-first, metadata-first by default.
- Git is the primary signal source.
- SQLite remains the single source of truth.
- Every insight remains inspectable (tool trace / reasoning trail).
- No hidden writes: KB edits and patch application stay explicitly confirmed.

Note: the PySide6 UI has been retired and removed from this repo. This doc now serves as the TS/Tauri architecture reference and historical record.

---

## Retired UI Surface (PySide6) — Historical

The PySide6 UI previously lived under `src/reos/gui/`, and has now been removed.

### Entry point
- `src/reos/gui/__init__.py` + `src/reos/gui/__main__.py`
  - Creates `QApplication`, installs exception hook, applies global QSS, shows `MainWindow`.

### Windows
- `src/reos/gui/main_window.py`:
  - **3-pane main window** (nav | chat | inspection)
  - Owns:
    - `Database` (`get_db()`)
    - `ChatAgent` (local Ollama tool-using agent)
    - Timers:
      - Every 30s: `poll_git_repo()` and then checks DB for `alignment_trigger` events
      - Commit review background thread (if enabled by settings)
  - Shows:
    - Chat conversation
    - Inspection pane with `AgentTrace` JSON
    - A guarded patch apply flow (only applies unified diff to `projects/<id>/kb/` paths)

- `src/reos/gui/projects_window.py` + `src/reos/gui/projects_widget.py`:
  - Projects are **filesystem-backed** under `projects/<project-id>/kb/`.
  - “Nothing is written without explicit, user-confirmed diff preview.”

- `src/reos/gui/settings_window.py` + `src/reos/gui/settings_widget.py`:
  - Ollama settings (URL + model)
  - Personas editor (system prompt + context + knobs)

### Styling
- `src/reos/gui/style.py`:
  - A single application-level QSS theme.

---

## Current Backend/Kernel Surfaces (Python)

### SQLite core
- `src/reos/db.py`:
  - Tables include: `events`, `repos`, `project_charter`, `agent_personas`, `app_state`.
  - The GUI today reads/writes via Python DB methods directly.

### Git observer + triggers
- `src/reos/git_poll.py`:
  - Polls git metadata (`status`, `diff --stat`) and inserts a `git_poll` event.

- `src/reos/storage.py`:
  - `append_event()` inserts to SQLite and may emit:
    - `alignment_trigger` (metadata-only heuristic)
    - `review_trigger` (context budget heuristic) — present but currently not called in `append_event()`

### Tool boundary (already close to UI-ready)
- `src/reos/mcp_tools.py` + `src/reos/mcp_server.py`:
  - A repo-scoped tool catalog backed by SQLite “active project”.
  - Exposes JSON-RPC over stdio (MCP-like): `tools/list`, `tools/call`.
  - Useful building block for a TS UI because it is:
    - local-only
    - schema’d
    - already sandboxed

### FastAPI scaffold (not yet UI-complete)
- `src/reos/app.py`:
  - Minimal endpoints: `/health`, `/events` ingest, `/reflections`, `/ollama/health`, `/tools`.
  - Missing for UI parity: chat endpoint, list events, project/persona CRUD, KB read/write.

---

## Recommended Target Architecture

### Keep Python as the “local kernel”
Do **not** reimplement Git polling, SQLite schema, and alignment heuristics in TS.
Instead:

- Python remains authoritative for:
  - SQLite schema + migrations
  - Git polling + checkpoint event emission
  - Tool execution + sandboxing
  - Agent/chat (Ollama)

- TypeScript becomes the **desktop shell**:
  - Layout + interaction
  - Rendering events/insights + inspection trails
  - Diff preview UX

This preserves the charter’s local-first + transparent reasoning intent, and minimizes migration risk.

### Two viable IPC options (choose one)

#### Option A (recommended for security + simplicity): stdio JSON-RPC to a Python kernel process
- TS app (Electron/Tauri) spawns `python -m reos.mcp_server` (or a dedicated “ui-kernel” entrypoint).
- UI talks JSON-RPC over stdio.

Pros:
- No localhost ports, no CORS, no network surface.
- Matches current “tool catalog” direction.
- Easy to package as a single child process.

Cons:
- You’ll likely add a few UI-specific RPC methods (chat, events stream, KB operations).

#### Option B: local HTTP (FastAPI) as the UI contract
- TS app spawns `python -m reos.app` and calls `http://127.0.0.1:<port>`.

Pros:
- Browser-like networking model; easy integration.
- Useful if you want multiple clients (desktop UI + CLI + future integrations).

Cons:
- Must handle auth token, port selection, and local attack surface.

**Recommendation:** Option A for the first migration (lowest surface area), then optionally expose a parallel HTTP layer later.

---

## What the TS UI Needs (contracts)

The PySide6 UI currently depends on:

1. **Chat**
   - Input: user message
   - Output: assistant message + `AgentTrace` (tool calls + tool results)

2. **Inspection**
   - Render the full trace as structured JSON

3. **Repo status + triggers**
   - Periodic git summary
   - Recent events, including `alignment_trigger` and `commit_review`

4. **Projects/KB**
   - List projects, browse KB file tree, edit a markdown page
   - Preview a unified diff and apply only after confirmation

5. **Settings**
   - Read/write Ollama URL + model
   - Personas CRUD, set active persona

### Minimal RPC surface to replicate current UX
If using stdio JSON-RPC, add (or adapt) methods roughly like:

- `reos_ui_health()`
- `reos_chat_respond({text}) -> {answer, trace}`
- `reos_state_get({key}) / reos_state_set({key,value})`
- `reos_persona_list / get / upsert / set_active`
- `reos_projects_list` (or reuse filesystem-based listing)
- `reos_kb_list_tree({project_id})`
- `reos_kb_read({path, start_line, end_line})`
- `reos_kb_write_preview({path, new_text}) -> {unified_diff}`
- `reos_kb_write_apply({path, new_text, confirmation_token})`

For the first Tauri cut, keep this even smaller: **chat/respond only**, with the trace rendered in the inspection pane. Event polling can be added after the shell stabilizes.

Note: you already have a strong start with `mcp_tools.py` for repo-scoped operations.

---

## Module Mapping (Python UI → TS UI)

| Python (today) | Responsibility | TS equivalent (proposed) |
|---|---|---|
| `gui/main_window.py` | 3-pane layout, chat + inspection, timers | `AppShell` with `NavPane`, `ChatPane`, `InspectionPane` |
| `gui/projects_widget.py` | KB tree + editor + diff-confirm writes | `ProjectsView` (tree + editor) + diff modal |
| `gui/settings_widget.py` | Ollama + persona settings | `SettingsView` (tabs) |
| `gui/style.py` (QSS) | global theme | CSS/Tailwind (match existing colors + spacing) |
| `agent.ChatAgent` | tool-using chat + trace | Kernel RPC `reos_chat_respond` |
| `storage.append_event` | event ingestion + trigger emission | remains in kernel; UI reads events |
| `mcp_tools.call_tool` | repo-scoped tools | use directly as underlying implementations |

---

## Migration Phases (low risk, no UX invention)

### Phase 0: Formalize the UI-kernel boundary
- Decide IPC: stdio JSON-RPC vs HTTP.
- Add kernel entrypoint tailored for UI (can reuse MCP server skeleton).
- Add missing kernel calls to support parity (chat, events list, settings/personas, KB operations).

Acceptance:
- A headless kernel process can perform:
  - `chat_respond`
  - `events_recent`
  - `persona get/set`
  - `kb read/write preview/apply`

### Phase 1: TS app replicates only the main 3-pane window
- Implement `NavPane`, `ChatPane`, `InspectionPane`.
- No projects/settings yet; keep them as separate buttons that open stub windows.

Acceptance:
- Chat works end-to-end, inspection shows trace.
- Alignment triggers appear as messages by reading recent `events`.

### Phase 2: Port Projects surface
- Implement KB tree + editor.
- Preserve explicit diff-confirm behavior.

Acceptance:
- No write occurs without diff preview confirmation.

### Phase 3: Port Settings surface
- Ollama URL/model; persona list/edit; set active.

### Phase 4: Retire PySide6 UI
- Keep Python kernel + TS UI.
- Optionally keep PySide6 as a dev fallback during transition.

---

## Packaging Notes (desktop reality)

- The TS desktop app should spawn the Python kernel and manage its lifecycle.
- Keep local data under `.reos-data/` (already in repo).
- Ensure the kernel uses the same DB path as today (`settings.data_dir / reos.db`).
- Logs: keep `.reos-data/reos.log` behavior consistent.

---

## Open Decisions

1. IPC: stdio JSON-RPC (recommended) vs local HTTP.
2. Event delivery: polling vs push (SSE/WebSocket). For MVP parity, polling is fine.
3. Where git polling runs:
   - Recommended: kernel runs polling + triggers on a timer.
   - UI should be a reader/render surface, not the observer.


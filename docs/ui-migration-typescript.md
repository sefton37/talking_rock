# UI: TypeScript Desktop App (Tauri)

## Goal

Run the **Talking Rock desktop UI** as a **TypeScript/Tauri app**, while keeping core principles intact:

- Local-first, privacy-first by default.
- SQLite remains the single source of truth.
- Every insight remains inspectable (tool trace / reasoning trail).
- No hidden writes.

Note: the PySide6 UI has been retired and removed. This doc serves as the TS/Tauri architecture reference.

---

## Architecture: Talking Rock Agents

The Tauri app provides the UI surface for three specialized agents:

| Agent | Purpose | UI Involvement |
|-------|---------|----------------|
| **CAIRN** | Attention minder (default) | Main chat, The Play navigation |
| **ReOS** | System agent | Command preview, system panel |
| **RIVA** | Coding agent | Diff preview, code execution |

---

## Current Backend/Kernel Surfaces (Python)

### SQLite Core
- `src/reos/db.py`:
  - Tables: `events`, `conversations`, `agent_personas`, `app_state`, `the_play`.
  - The GUI reads/writes via Python DB methods directly.

### Agent Layer
- `src/reos/agent.py`:
  - Tool-using chat agent, routes between CAIRN/ReOS/RIVA.

### Tool Boundary (UI-ready)
- `src/reos/mcp_tools.py` + `src/reos/mcp_server.py`:
  - Tool catalog for Linux, code, and CAIRN operations.
  - JSON-RPC over stdio (MCP-like): `tools/list`, `tools/call`.

### FastAPI Scaffold
- `src/reos/app.py`:
  - Endpoints: `/health`, `/events`, `/reflections`, `/ollama/health`, `/tools`.
  - Missing for full parity: some CRUD operations.

---

## Recommended Target Architecture

### Keep Python as the "local kernel"

- Python remains authoritative for:
  - SQLite schema + migrations
  - Tool execution + sandboxing
  - Agent/chat (Ollama)
  - CAIRN, ReOS, RIVA logic

- TypeScript becomes the **desktop shell**:
  - Layout + interaction
  - Rendering events/insights + inspection trails
  - Diff preview UX
  - Command approval workflow

This preserves local-first + transparent reasoning, and minimizes migration risk.

### IPC: stdio JSON-RPC (Recommended)

TS app (Tauri) spawns `python -m reos.ui_rpc_server` and talks JSON-RPC over stdio.

Pros:
- No localhost ports, no CORS, no network surface.
- Matches current tool catalog direction.
- Easy to package as a single child process.

---

## What the TS UI Needs (contracts)

1. **Chat**
   - Input: user message
   - Output: assistant message + `AgentTrace` (tool calls + results)

2. **Inspection**
   - Render the full trace as structured JSON

3. **System Panel (ReOS)**
   - Live system metrics
   - Service/container status
   - Command preview and approval

4. **The Play (CAIRN)**
   - Navigate Acts/Scenes/Beats
   - View/edit KB content
   - Preview diffs before applying

5. **Code Mode (RIVA)**
   - Diff preview for code changes
   - Execution streaming
   - Contract/verification status

6. **Settings**
   - Read/write Ollama URL + model
   - Personas CRUD, set active persona

### Minimal RPC Surface

Using stdio JSON-RPC:

- `reos_ui_health()`
- `reos_chat_respond({text}) -> {answer, trace}`
- `reos_state_get({key}) / reos_state_set({key,value})`
- `reos_persona_list / get / upsert / set_active`
- `reos_play_list_tree()` - The Play navigation
- `reos_kb_read({path})`
- `reos_kb_write_preview({path, new_text}) -> {unified_diff}`
- `reos_kb_write_apply({path, new_text, confirmation_token})`

For first Tauri cut: **chat/respond only**, with trace in inspection pane.

---

## Module Mapping (Python → TS UI)

| Python | Responsibility | TS equivalent |
|--------|----------------|---------------|
| `agent.py` | Tool-using chat + trace | `reos_chat_respond` RPC |
| `cairn/` | Attention minder, The Play | `PlayNavigator` component |
| `linux_tools.py` | ReOS system tools | `SystemPanel` component |
| `code_mode/` | RIVA coding tools | `DiffPreview`, `ExecutionStream` |
| `db.py` | SQLite operations | Kernel RPC calls |
| `ui_rpc_server.py` | JSON-RPC bridge | Direct communication |

---

## Migration Phases

### Phase 0: Formalize UI-kernel boundary
- Decide IPC: stdio JSON-RPC vs HTTP (recommend stdio).
- Add kernel entrypoint tailored for UI.
- Add missing kernel calls for full parity.

### Phase 1: TS app replicates 3-pane window
- Implement `NavPane`, `ChatPane`, `InspectionPane`.
- Chat works end-to-end, inspection shows trace.

### Phase 2: Port System Panel (ReOS)
- Live metrics, service status.
- Command preview/approval workflow.

### Phase 3: Port The Play (CAIRN)
- Acts/Scenes/Beats navigation.
- KB editor with diff-confirm behavior.

### Phase 4: Port Code Mode (RIVA)
- Diff preview for code changes.
- Execution streaming UI.

### Phase 5: Port Settings
- Ollama URL/model.
- Persona management.

---

## Packaging Notes

- TS desktop app spawns Python kernel, manages lifecycle.
- Local data in `.reos-data/` (already established).
- Kernel uses `settings.data_dir / reos.db`.
- Logs: `.reos-data/reos.log`.

---

## Open Decisions

1. IPC: stdio JSON-RPC (recommended) vs local HTTP.
2. Event delivery: polling vs push (SSE/WebSocket). Polling fine for MVP.
3. System state updates: kernel provides, UI renders.

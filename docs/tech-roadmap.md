## ReOS Technical Roadmap (Python, Local-First)

### Scope and Intent
- Build a local Python-based “attention kernel” for developer workflows on Linux, aligned with the ReOS charter: no cloud dependency, user-owned data, zero telemetry by default.
- MVP focus: a project manager for local development that mirrors attention patterns and verifies Copilot I/O in real time while “vibe coding” in VS Code.
- Avoid task scoring, streaks, or engagement loops; all reflections are descriptive and explainable.
- Operate alongside a local Ollama server for LLM calls (local-only by default); keep the LLM layer swappable later.
- Plan to expose MCP tools so a co-agent (project manager) can steer decisions and keep work charter-compliant.

### Guardrails from the Charter
- No hidden data capture; require explicit consent for any data leaving the machine.
- Language: reflective, non-moral. Report fragmentation/coherence, not productivity scores.
- Data boundaries: default to local storage (SQLite/JSONL). No message-body capture from editors or email; only metadata needed for attention modeling.
- Thunderbird (future) integration must respect metadata-only defaults.

### Assumptions
- OS: Linux; Editor: VS Code (user already using Copilot).
- Language: Python 3.12.3 (existing .venv at `/home/kellogg/dev/ReOS/.venv`); package manager: pip/venv by default to match the current env (uv can be added later if desired).
- No existing codebase; this roadmap seeds the first implementation.

### Architecture Direction (explainable, inspectable)
- **Event collectors (local)**: VS Code extension → local WebSocket/HTTP bridge; Git activity watcher; optional window focus watcher (e.g., `python-xlib`/`libinput`).
- **Classifier layer**: transparent heuristics labeling sessions as coherent vs fragmented, revolution vs evolution; surface a “frayed mind” flag when rapid switching is detected.
- **Storage**: local SQLite with WAL under the repo (e.g., `./.reos-data/db.sqlite3`), plus an audit log. All tables have created_at/ingested_at for auditability. No data leaves the machine.
- **Interfaces**: CLI/TUI (Textual) for reflections; lightweight local HTTP API (FastAPI) for extension communication; optional minimal web UI served locally.
- **Privacy switches**: global kill-switch, per-source toggles, explicit “no content capture” enforced at collectors.
- **LLM layer**: local Ollama endpoint by default; abstracted client so alternative local models can be swapped in without cloud calls.
- **MCP hooks**: design service endpoints and schemas so MCP tools can expose ingestion, reflection, and config operations to a project-manager co-agent.

### MVP Thin Slice
1) Local service: FastAPI + uvicorn, packaged with uv; health, `/events` ingest, `/reflections` query; logging is local-only.
2) VS Code bridge: minimal extension that mirrors Copilot prompts/responses and user edits to the local service (with an on/off toggle and in-UI indicator). No network beyond `localhost`.
3) Heuristics v0: sessionization by active repo and window focus; fragmentation score = switches per 5–10 minute window; flag “frayed mind” when switches exceed threshold and depth time < target.
4) Reflections surface: CLI command `reos reflect --since 2h` showing timeline of contexts, switches, and Copilot I/O echo for verification.
5) Storage v0: SQLite schema with `events` (source, payload_metadata, ts), `sessions`, `classifications`, `audit_log`.
6) LLM plumbing v0: thin client to local Ollama with explicit model selection and a “no network” guard; scoped to summarization/explanation requests only.
7) MCP-ready interfaces: document endpoints and payloads so a project-manager co-agent can audit events and nudge decisions in VS Code.

### Incremental Milestones
- **M0 (Scaffold)**: repo init, uv/venv setup, FastAPI skeleton, config file with privacy defaults, SQLite migrations.
- **M1 (VS Code bridge)**: extension with status icon + command palette toggle; sends Copilot prompt/response metadata and file URI/event timestamps to local API; user-visible audit pane.
- **M2 (Attention heuristics)**: implement fragmentation/coherence classifier and revolution/evolution labeling; expose explain-why payloads.
- **M3 (Reflections UX)**: Textual-based TUI to browse sessions and Copilot I/O echoes; export-to-markdown locally.
- **M4 (Thunderbird prep)**: stub collector interface that only ingests headers/metadata; keep disabled by default until configured.

### Development Workflow (proposed)
- Tooling: pip + venv already present; add `ruff` + `mypy` for lint/typecheck, `pytest` for tests. `uv` can be introduced later if we want lockfile speed.
- Commands (once tools are in place): `/home/kellogg/dev/ReOS/.venv/bin/python -m uvicorn reos.app:app --reload` (service), `/home/kellogg/dev/ReOS/.venv/bin/python -m pytest`, `ruff check .`, `mypy .`.
- Observability: structured logging to stdout + rotating file in `./.reos-data/logs`; redact content fields by default.

### VS Code + Copilot I/O Verification Plan
- Extension (approved) subscribes to inline completion and chat events, mirrors minimal metadata (prompt, response summary hash, timestamp, file URI) to `localhost` API; user can open an “Attention pane” to see what was sent/received.
- Local service stores mirrored events and links them to sessions; CLI/TUI renders a synchronized timeline so the user can double-check Copilot I/O in real time.
- Provide an “airplane mode” toggle in both the extension and the service to halt all ingestion instantly.

### Notes on VS Code/Copilot Observability
- VS Code extensions can reliably capture **editor activity metadata** (active file, saves, timestamps). Direct access to GitHub Copilot’s internal prompt/response stream may be limited by VS Code APIs; plan to implement “Copilot I/O verification” via explicit user-visible hooks (e.g., a dedicated panel and/or explicit capture commands) rather than hidden interception.

### Open Questions to Confirm
- Retention policy: currently open-ended; will optimize later (size/time caps for `./.reos-data` to be decided once usage is clearer).
- Dependencies: FastAPI/Starlette are acceptable; no extra constraints noted.
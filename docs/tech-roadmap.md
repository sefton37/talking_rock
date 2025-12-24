## ReOS Technical Roadmap (Python, Local-First, Git Companion + Life Reflection)

### Scope and Intent

ReOS is a **Git-companion intelligence system**:

- **Git Repo (Primary Signal Source)**: ReOS observes your working tree and commits locally (status, diffstat, diffs by opt-in).
- **ReOS Desktop App (Companion)**: Sits alongside your editor as a reflection + reasoning tool. It surfaces gentle checkpoints when your changes appear to drift from the charter/roadmap or split into too many threads.
- **Unified Workflow**: Build anywhere (editor of choice), reflect in ReOS. Data flows from Git → SQLite → ReOS reasoning + UI.
- **Evolution**: Starts as a Git companion for dev work, expands into broader life/attention reflection.

**Core Philosophy**: Attention is labor and sacred. ReOS protects it by observing with clarity, reflecting with compassion, and returning agency to the user.

### Guardrails from the Charter

- No hidden data capture; require explicit consent for any data leaving the machine.
- Language: reflective, non-moral. Report observed signals (switching, change scope), not productivity scores.
- Data boundaries: default to local storage (SQLite). No file content capture; only metadata (filename, time, git commit).
- Transparency: every AI-generated output includes its "inspection trail" (prompt sent, model used, tool calls made, confidence, alternatives considered).
- Checks & Balances: proactive, compassionate nudges. Not commands, not guilt—just "notice this" and "what's your intention?"

### Assumptions

- OS: Linux; dual-window workflow (editor + ReOS).
- Language: Python 3.12.3 (kernel/reasoning); TypeScript/Tauri for ReOS UI.
- Ollama runs locally; model user-selected.
- Git is the primary data collector; ReOS is the companion + reflection layer.
- All events flow through SQLite; no direct cloud calls.

### Architecture Direction (Bifocal, Observation-Driven)

**Git Observer** (ReOS local poller):
- Polls repo metadata locally: `git status`, `git diff --stat`, `git diff --numstat`.
- Optionally (explicit opt-in), includes limited `git diff` text for LLM review.
- Writes observation events to SQLite → no user interruption.

**ReOS Desktop App** (Companion):
- Left nav: observed repos + current working tree state.
- Center: real-time attention dashboard + reflection chat.
- Right inspection pane: click on any insight → see full reasoning trail.
- Proactive prompts: "alignment checkpoint" when changes suggest drift or too many threads.

**SQLite Core**:
- Events table: git status/diff metadata + checkpoint events.
- Sessions table: project-aware work periods.
- Classifications table: explainable labels (e.g., switching level, revolution/evolution) derived from signals.
- Audit_log table: all AI reasoning + user reflections.

**LLM Layer**:
- Command registry is repo-centric: alignment review of changes vs tech roadmap + charter.
- System prompt includes (a) charter + roadmap, (b) git change summary, (c) optional diffs by opt-in.
- Reasoning is always transparent and auditable.

**Interfaces**:
- Primary: ReOS desktop app (reflection + checks/balances).
- Secondary: none required.
- Future: CLI reflect command; life graph visualization; broader attention tracking (email, browser, OS).

### MVP Thin Slice (Bifocal Workflow)

1. **Git Polling**: Local repo polling → SQLite.
2. **ReOS Dashboard**: Display working tree status + change scope.
3. **Signals (Not Judgments)**: Track change breadth/scope signals; show neutral signals in ReOS.
4. **Quiet Background Questions** (core):
	- Are we drifting from roadmap/charter (changes vs docs)?
	- Are we taking on too many threads (change breadth + multi-area edits)?
5. **Proactive Checkpoints**: When those signals cross thresholds, ReOS surfaces a gentle "alignment checkpoint" prompt.

### Incremental Milestones

- **M0 (Completed)**: FastAPI scaffold, JSONL storage, Ollama health check, tool registry.
- **M1 (In Progress)**: SQLite migration, ReOS desktop app with 3-pane layout, command registry scaffolded.
- **M1b (Next)**: Git polling loop → SQLite; ReOS nav pane populated from repo status.
- **M2 (Real-time Signals)**: Switching/time signals + change-scope signals; proactive "alignment checkpoint" prompts.
- **M3 (Reflection & Reasoning)**: Ollama review of changes vs roadmap/charter; inspection pane shows full reasoning trail.
- **M4 (Classification)**: Revolution/evolution, coherence/fragmentation classification; reflections learned + remembered.
- **M5 (Life Expansion)**: Optional: Email (Thunderbird), browser, OS integration; broader life graph + attention management.

### Development Workflow

- Tooling: ruff, mypy, pytest (already set up).
- Desktop UI: `./reos` (Tauri dev UI), `python -m reos.app` (service), `python -m pytest` (tests).
- Dependencies: Ollama (local), plus Tauri prerequisites for the desktop shell.

### Key Design Decisions

1. **Git as Primary Observer**: Don't ask users to manually input their work; observe repo changes locally.
2. **No Interruption UI**: ReOS stays companion; checkpoints are gentle and throttled.
3. **Signals Come From Git**: Don't infer intent from metadata alone; use change summary + opt-in diffs.
4. **LLM Anchors to Plan**: Intent and "too many threads" are assessed by reviewing changes against roadmap + charter.
5. **Data Stays Local**: All SQLite, no cloud sync for core MVP.

### Open Questions

1. How sensitive should drift/thread checkpoints be to avoid noise?
2. Should user reflections ("This was exploration") be saved as training data for future classifications?
3. Email/browser integration: opt-in or opt-out by default?

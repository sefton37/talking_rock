# ReOS Workflow Example: Git Repo ↔ ReOS Companion

## Conceptual Overview

ReOS is a companion to a **Git repository**, not a VS Code extension.

It observes repo state locally (working tree + commits) and quietly evaluates two plan-anchored questions in the background:

1. **Drift**: Do the current changes still map to the charter + tech roadmap?
2. **Threads**: Are we opening too many parallel threads at once (breadth/scope of changes)?

By default, ReOS is **metadata-first** (status/diffstat/numstat). Including diff text for deeper LLM review is an explicit opt-in.

---

## The Human-Centered Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                          HUMAN ATTENTION                            │
│                       (Primary Agency)                              │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
                 Developer edits
               (any editor/IDE)
                       │
                       ▼
                 Git working tree
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                               ReOS                                  │
│  Polls repo → stores events → triggers checkpoints (gentle, throttled)│
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
                    SQLite
              (events + audit_log)
                       │
                       ▼
                Reflection + choice
       (run alignment review / note intention)
```

ReOS does not infer “distracted” from telemetry. It stays anchored to:

- the charter (values)
- the tech roadmap (plan)
- the observed code changes (git)

---

## Concrete Example Scenario

**Time**: 2:00 PM – 2:20 PM

### Phase 1: Work begins (repo changes accumulate)

ReOS runs locally and periodically polls:

- `git status --porcelain`
- `git diff --stat`
- `git diff --numstat`

It stores a metadata-only snapshot event:

```json
{
  "kind": "git_poll",
  "repo": "/home/user/dev/ReOS",
  "branch": "main",
  "changed_files": [
    "src/reos/alignment.py",
    "docs/tech-roadmap.md"
  ],
  "diff_stat": "2 files changed, 31 insertions(+), 6 deletions(-)",
  "ts": "2025-12-17T14:03:30Z"
}
```

### Phase 2: ReOS evaluates drift + thread breadth

ReOS compares current changes to:

- `docs/tech-roadmap.md`
- `ReOS_charter.md`

Signals include:

- how many changed files are not referenced/anchored in roadmap/charter
- how many distinct areas are being touched (e.g. `src/`, `docs/`, `tests/`)
- change magnitude (numstat) and context-budget pressure

### Phase 3: ReOS surfaces a gentle checkpoint

When thresholds are crossed (with cooldown), ReOS emits an `alignment_trigger` event and the GUI displays a short prompt:

- “Quick checkpoint: your current changes may be opening multiple threads or drifting from the roadmap/charter. Want to run `review_alignment`?”

### Phase 4: Deeper review (LLM cites code changes)

For deeper determination, ReOS can run an alignment review that:

- summarizes changes and cites diffs (opt-in)
- answers (with transparency):
  - what changed
  - where it maps (or doesn’t) to roadmap/charter
  - whether multiple threads are open

---

## What ReOS avoids

- No editor extension requirement.
- No “distraction” labeling from metadata.
- No file-content capture by default.

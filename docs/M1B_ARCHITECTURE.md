# M1b Architecture (Git Companion)

M1b pivots ReOS to be a companion to **Git**, not a companion to a specific editor.

## Core Loop

- ReOS polls the configured repo (local-only):
  - `git status --porcelain`
  - `git diff --stat`
  - `git diff --numstat`
- Stores `git_poll` events in SQLite.
- Runs alignment heuristics that ask two questions:
  1) **Drift**: do current changes map to `docs/tech-roadmap.md` and `ReOS_charter.md`?
  2) **Threads**: are changes spread across too many areas/files (multiple threads)?
- Emits throttled checkpoint events:
  - `review_trigger` (context budget pressure)
  - `alignment_trigger` (drift/thread breadth signals)

## Data Boundaries

- Default is metadata-first.
- Including diff text for the LLM is an explicit opt-in.
- All data stays local; no cloud calls.

## UI

- Left nav shows repo state (branch, changed files count, diffstat).
- Center chat shows gentle checkpoint prompts.
- Right inspection pane will show full reasoning trails (M3).

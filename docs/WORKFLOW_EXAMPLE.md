# ReOS Workflow Example: VSCode Extension ↔ ReOS Companion

## Conceptual Overview

This document walks through a **real-world example** of how the VSCode extension bridges to ReOS, showing exactly what data flows between systems and how the human is positioned at the center of the interaction loop.

---

## The Human-Centered Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                          HUMAN ATTENTION                            │
│                       (Primary Agency)                              │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
         ┌─────────────┴──────────────┐
         │                            │
         ▼                            ▼
    VSCode              ←→        ReOS GUI
  (Workspace)         (Extension)    (Companion)
    Active             Observes     Reflects
    Editor             & Tracks     & Prompts
         │                            │
         └─────────────┬──────────────┘
                       │
         ┌─────────────┴──────────────┐
         │                            │
         ▼                            ▼
   SQLite Store             User Reflection
   (Events Table)          (Intention Choice)
                                │
                                ▼
                          SQLite audit_log
                        (Learning Store)
```

**Key Principle**: The human is not a passive consumer. The human is the agent making intentional choices. ReOS and VSCode are tools that help the human see their attention patterns and decide.

---

## Concrete Example Scenario

**Time**: 2:00 PM - 2:15 PM
**Human Activity**: Working on a backend API, then switching to frontend, then checking a bug in backend

### **Phase 1: Human Starts Coding in VSCode** (2:00 PM)

**What the human does:**
```
1. Opens VSCode
2. VSCode extension activates silently
3. Human opens file: backend/src/main.py
4. Human starts editing (adds route handler)
```

**What the VSCode Extension captures:**

When `onDidChangeActiveTextEditor` fires (human opens `main.py`):
```json
{
  "kind": "active_editor",
  "source": "vscode-extension",
  "timestamp": "2024-12-17T14:00:15Z",
  "projectName": "backend",
  "uri": "file:///dev/backend/src/main.py",
  "languageId": "python",
  "workspaceFolder": "/dev/backend",
  "editorChangeTime": "2024-12-17T14:00:15Z"
}
```

**What gets stored in SQLite:**
```sql
INSERT INTO events (
  id, source, kind, ts, payload_metadata, created_at, ingested_at
) VALUES (
  'evt-001',
  'vscode-extension',
  'active_editor',
  '2024-12-17T14:00:15Z',
  '{"uri":"file:///dev/backend/src/main.py","projectName":"backend",...}',
  '2024-12-17T14:00:15Z',
  '2024-12-17T14:00:15Z'
);
```

**ReOS is silent.** No interruption. Just observing.

---

### **Phase 2: Every 10 Seconds, Extension Publishes Heartbeat**

**At 2:00:25 PM** (10 seconds after file open):

The extension publishes a heartbeat event:
```json
{
  "kind": "heartbeat",
  "source": "vscode-extension",
  "timestamp": "2024-12-17T14:00:25Z",
  "projectName": "backend",
  "uri": "file:///dev/backend/src/main.py",
  "timeInFileSeconds": 10,
  "fileHistoryCount": 1,
  "editorChangeTime": "2024-12-17T14:00:15Z"
}
```

**Stored in SQLite**: Same pattern, `kind: "heartbeat"`

**Why heartbeat?** It tells ReOS: "The human is still in this file. 10 seconds have elapsed. They're in the zone."

**At 2:00:35 PM** (10 more seconds):
```json
{
  "timeInFileSeconds": 20,
  ...
}
```

---

### **Phase 3: Human Switches to Frontend** (2:03 PM)

**What the human does:**
```
1. Click on sidebar to open frontend project
2. Open file: frontend/src/components/Button.tsx
3. Start editing component
```

**What the Extension captures:**

`onDidChangeActiveTextEditor` fires again:
```json
{
  "kind": "active_editor",
  "source": "vscode-extension",
  "timestamp": "2024-12-17T14:03:00Z",
  "projectName": "frontend",
  "uri": "file:///dev/frontend/src/components/Button.tsx",
  "languageId": "typescript",
  "workspaceFolder": "/dev/frontend",
  "editorChangeTime": "2024-12-17T14:03:00Z"
}
```

**Extension also tracks in fileEventHistory:**
```javascript
fileEventHistory = [
  {timestamp: 14:00:15, uri: "backend/src/main.py"},
  {timestamp: 14:03:00, uri: "frontend/src/components/Button.tsx"}
]
```

**Stored in SQLite**: New row with `projectName: "frontend"`

---

### **Phase 4: ReOS Nav Pane Auto-Refreshes** (2:03:30 PM)

**Timer fires**: Every 30 seconds, nav pane refresh triggers.

**ReOS calls** `get_current_session_summary(db)`:

1. Queries SQLite for last 100 events
2. Extracts:
   ```
   Events in last 3.5 minutes:
   - backend/main.py: 180 seconds (3 min)
   - frontend/Button.tsx: 30 seconds
   ```

3. Calls `calculate_fragmentation()` on last 5 minutes:
   ```
   - 2 file switches detected
   - 2 unique files
   - Switch threshold: 8
   - Score: (2 switches / 8 threshold) = 0.25
   - Explanation: "Coherent focus: 2 switches across 2 files."
   ```

**ReOS Nav Pane displays:**
```
┌────────────────────────────────────┐
│ VSCode Projects                    │
├────────────────────────────────────┤
│ Fragmentation: 25%                 │
│                                    │
│ ✓ backend: 1 file, 3m              │
│ ✓ frontend: 1 file, 0m             │
└────────────────────────────────────┘
```

**The human sees this** but ReOS doesn't interrupt. It's just information available.

---

### **Phase 5: Rapid Switching Occurs** (2:05-2:10 PM)

**What the human does:**
```
2:05:00 → Switch to backend/utils.py
2:05:30 → Switch to backend/models.py
2:06:00 → Switch to frontend/App.tsx
2:06:30 → Switch to backend/config.py
2:07:00 → Switch to backend/main.py (again)
2:07:30 → Switch to frontend/index.tsx
2:08:00 → Switch to backend/utils.py (again)
2:08:30 → Switch to frontend/Button.tsx (again)
```

**Extension tracks all 8 switches in fileEventHistory**

**8 new active_editor events stored in SQLite**

**At 2:08:30 PM**, nav pane refreshes:

**ReOS calls** `calculate_fragmentation()` on last 5 minutes:
```
- 8 file switches detected
- 4 unique files
- Switch threshold: 8
- Score: 8/8 = 1.0 (fully fragmented)
- Explanation: "Fragmented attention: 8 switches across 4 files in 300s. 
              Intention check: is this exploration or distraction?"
```

**ReOS Nav Pane now shows:**
```
┌────────────────────────────────────┐
│ VSCode Projects                    │
├────────────────────────────────────┤
│ Fragmentation: 100% ⚠️             │
│                                    │
│ ✓ backend: 4 files, 4m             │
│ ✓ frontend: 2 files, 3m            │
└────────────────────────────────────┘
```

---

### **Phase 6: Human Notices & Reflects** (2:09 PM)

**What the human does:**
```
1. Glances at ReOS nav pane
2. Sees "Fragmentation: 100%" and switching pattern
3. Reads explanation: "Is this exploration or distraction?"
4. Realizes: "Oh, I was context-switching a lot. Let me check my intention."
5. Clicks on fragmentation indicator to open reflection panel
```

**ReOS Reflection Panel opens:**
```
┌──────────────────────────────────────────┐
│ Attention Reflection                     │
├──────────────────────────────────────────┤
│                                          │
│ Last 5 minutes analysis:                 │
│                                          │
│ • 8 context switches                     │
│ • Across 4 files in 2 projects           │
│ • Fragmentation score: 100%              │
│                                          │
│ Pattern: "This looks like rapid          │
│ exploration across many contexts."       │
│                                          │
│ Question:                                │
│ ┌──────────────────────────────────────┐ │
│ │ What was your intention with this    │ │
│ │ switching? Choose one:               │ │
│ │                                      │ │
│ │ [A] Creative exploration             │ │
│ │ [B] Investigating a complex bug      │ │
│ │ [C] Unplanned fragmentation          │ │
│ │ [D] Testing across systems           │ │
│ └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

**The human chooses**: [A] Creative exploration

---

### **Phase 7: Human's Reflection Stored** (2:09:30 PM)

**ReOS calls** `handle_note()` command:

```python
# User selected intention
db.insert_event(
  event_id='evt-reflection-001',
  source='user',
  kind='reflection_note',
  ts='2024-12-17T14:09:30Z',
  payload_metadata=json.dumps({
    "intention": "creative_exploration",
    "fragmentation_score": 1.0,
    "context": "switching between backend and frontend"
  }),
  note="Intentional exploration across backend API and frontend components"
)
```

**Stored in SQLite audit_log**: User's intentional choice documented

**ReOS responds:**
```
✅ Intention recorded: "Creative exploration across backend/frontend"

Next time you have similar switching patterns, I'll remember this.
You were intentional then; you can be intentional now.
```

---

### **Phase 8: Later in Day, Similar Pattern Detected** (3:30 PM)

**Human is switching between files again** (7 switches in 5 min)

**ReOS calls** `calculate_fragmentation()`:
```
Score: 0.875 (highly fragmented)
```

**But now ReOS has learned context:**

From audit_log, it knows:
- Similar pattern at 2:05-2:10 PM
- Human called it "creative exploration"
- Not negative; intentional

**ReOS Reflection Panel shows:**
```
Pattern detected: Similar to earlier today.

⭐ Earlier, you called this "creative exploration."
   You were switching between backend and frontend
   while investigating API design.

This switching looks similar. Are you:
  [A] In another exploration phase?
  [B] This time unplanned?
  [C] Deep focus in one area now?
```

**The human sees their own past reasoning reflected back.** This enables learning.

---

## Complete Data Flow Diagram

```
                        ┌─────────────────┐
                        │   HUMAN WORK    │
                        │  (VSCode)       │
                        │                 │
                        │ Edit files,     │
                        │ switch projects │
                        └────────┬────────┘
                                 │
                                 │ User takes action
                                 │ (file focus change)
                                 │
                   ┌─────────────▼──────────────┐
                   │  VSCode Extension          │
                   │  (Silent Observer)         │
                   │                            │
                   │ • Captures file focus      │
                   │ • Extracts project name    │
                   │ • Publishes heartbeat      │
                   │ • Tracks history           │
                   └─────────────┬──────────────┘
                                 │
                                 │ Events published
                                 │ (sub-second latency)
                                 │
                   ┌─────────────▼──────────────┐
                   │  FastAPI Service           │
                   │  POST /events              │
                   │                            │
                   │ Receives: active_editor,   │
                   │           heartbeat, etc   │
                   └─────────────┬──────────────┘
                                 │
                                 │ Events persisted
                                 │
                   ┌─────────────▼──────────────┐
                   │  SQLite Local Store        │
                   │  (.reos-data/main.db)      │
                   │                            │
                   │ Tables:                    │
                   │ • events (all VSCode       │
                   │   activity)                │
                   │ • sessions (work periods)  │
                   │ • classifications          │
                   │ • audit_log (reflections)  │
                   └──┬──────────────────┬──────┘
                      │                  │
         ┌────────────▼─┐         ┌──────▼───────────┐
         │ Attention    │         │ ReOS GUI          │
         │ Module       │         │ (Companion)       │
         │              │         │                   │
         │ Calculates:  │         │ • Nav Pane        │
         │ • Fragment   │         │ • Chat interface  │
         │ • Projects   │         │ • Metrics display │
         │ • Pattern    │         │                   │
         └────────────┬─┘         └────────┬──────────┘
                      │                    │
                      └────────┬───────────┘
                               │
                    ┌──────────▼──────────┐
                    │  Human Sees:        │
                    │  • Projects list    │
                    │  • Fragmentation    │
                    │    score            │
                    │  • Reflection       │
                    │    prompts          │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Human Chooses:      │
                    │ • Intention         │
                    │ • Reflection        │
                    │ • Next action       │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ SQLite audit_log    │
                    │                     │
                    │ Stores:             │
                    │ • Intention choice  │
                    │ • Reflection note   │
                    │ • User context      │
                    └─────────────────────┘
```

---

## Data Structure Examples

### Event: File Switch
```json
{
  "kind": "active_editor",
  "source": "vscode-extension",
  "timestamp": "2024-12-17T14:03:00Z",
  "projectName": "frontend",
  "uri": "file:///dev/frontend/src/components/Button.tsx",
  "languageId": "typescript",
  "workspaceFolder": "/dev/frontend",
  "editorChangeTime": "2024-12-17T14:03:00Z"
}
```

### Event: Heartbeat (Time-in-file tracking)
```json
{
  "kind": "heartbeat",
  "source": "vscode-extension",
  "timestamp": "2024-12-17T14:00:25Z",
  "projectName": "backend",
  "uri": "file:///dev/backend/src/main.py",
  "timeInFileSeconds": 10,
  "fileHistoryCount": 2
}
```

### Fragmentation Metrics (Computed)
```json
{
  "fragmentation_score": 1.0,
  "switch_count": 8,
  "unique_files": 4,
  "window_seconds": 300,
  "explanation": "Fragmented attention: 8 switches across 4 files in 300s. Intention check: is this exploration or distraction?"
}
```

### Session Summary (Computed)
```json
{
  "status": "active",
  "total_duration_seconds": 600,
  "projects": [
    {
      "name": "backend",
      "file_count": 4,
      "estimated_duration_seconds": 360
    },
    {
      "name": "frontend",
      "file_count": 2,
      "estimated_duration_seconds": 240
    }
  ],
  "fragmentation": {
    "score": 1.0,
    "switches": 8,
    "explanation": "Fragmented attention..."
  }
}
```

### User Reflection (Stored in audit_log)
```json
{
  "kind": "reflection_note",
  "source": "user",
  "timestamp": "2024-12-17T14:09:30Z",
  "payload_metadata": {
    "intention": "creative_exploration",
    "fragmentation_score": 1.0,
    "context": "switching between backend and frontend",
    "note": "Intentional exploration across backend API and frontend components"
  }
}
```

---

## Key Interaction Principles

### 1. **Silence by Default**
The extension never interrupts. It observes. The human controls when to look at ReOS.

### 2. **Transparency**
Every metric shows its calculation:
- "Fragmentation: 8 switches across 4 files in 300s"
- Not: "Your productivity is 62%"

### 3. **Human Agency**
The human chooses their intention. ReOS reflects patterns. The human decides.

### 4. **Local & Safe**
All data stays in `.reos-data/`. No cloud. User owns everything.

### 5. **Learning from Reflection**
When the human says "This was intentional exploration," ReOS remembers. Next similar pattern includes that context.

### 6. **Compassionate Language**
- ❌ "You were distracted."
- ✅ "8 switches in 5 minutes. What was your intention?"

---

## The Three Phases of Interaction

### **Phase 1: Observation** (Extension → SQLite)
- Silent, continuous
- Human doesn't need to do anything
- All data captured automatically

### **Phase 2: Reflection** (ReOS analyzes & displays)
- Human optionally looks at ReOS
- Sees metrics, patterns, fragmentation
- No judgment; just information

### **Phase 3: Intention** (Human reflects & responds)
- Human chooses to respond to prompt
- Stores their intention
- ReOS learns from their choice

**Then loop repeats**: Observation → Reflection → Intention → Learning

---

## Why This Design?

**Problem**: Productivity tools interrupt. They guilt. They optimize for tools, not humans.

**ReOS Solution**:
1. **Observation without interruption**: Extension silent by default
2. **Reflection without judgment**: Metrics transparent, language compassionate
3. **Agency preserved**: Human chooses when to reflect, what their intention is
4. **Learning from context**: Each reflection informs future analysis

**Result**: Attention treated as labor, not a score to optimize. Humans see their patterns, choose intentionally, and ReOS learns from their wisdom.

---

## Next Steps: The Human's Choice

At any point, the human can:

- **Ignore metrics**: Keep coding. ReOS stays out of the way.
- **Reflect briefly**: Check nav pane. See fragmentation. Continue.
- **Reflect deeply**: Open reflection panel. Answer intention questions. Store insights.
- **Ask LLM**: "Help me understand this switching pattern." (Ollama integration coming M3)

**The human is always in control. ReOS is always a companion, never a commander.**

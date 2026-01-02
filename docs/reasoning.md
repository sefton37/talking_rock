# ReOS Extended Reasoning and Planning System

The reasoning system provides intelligent planning for complex Linux operations while keeping simple requests fast and natural.

## Overview

When you ask ReOS to do something, it first assesses the complexity:

- **Simple requests** (like "show disk space") execute immediately
- **Complex requests** (like "speed up boot time") get planned first
- **Risky requests** (like "delete all temp files") require explicit approval

## How It Works

### 1. Complexity Assessment

Every request is classified into one of four categories:

| Level | Examples | Behavior |
|-------|----------|----------|
| **Simple** | "install htop", "show memory" | Execute directly |
| **Complex** | "set up development environment" | Create plan, show steps |
| **Diagnostic** | "why is my laptop hot" | Investigate first, then suggest |
| **Risky** | "delete all logs" | Warn, show impact, require approval |

### 2. Task Planning

For complex requests, ReOS creates a step-by-step plan:

```
You: speed up my boot time

ReOS: Let me check what's slowing it down first...

Found three bottlenecks:
1. NetworkManager waits 90s for network (you're on wifi, don't need this)
2. snapd taking 12s (you're not using snaps)
3. Old bluetooth service running (you don't have bluetooth)

I can disable these safely. Should take about 30 seconds and won't
affect anything you use. Want me to go ahead?
```

### 3. Safe Execution

During execution:
- Each step is verified before moving to the next
- Config files are backed up before modification
- Rollback commands are recorded for each change
- If something fails, previous changes can be undone

### 4. Natural Conversation

The system speaks naturally, not robotically:

**Bad (robotic):**
```
ANALYZING REQUEST...
COMPLEXITY LEVEL: HIGH
GENERATING EXECUTION PLAN...
STEP 1 OF 7: INITIATING...
```

**Good (natural):**
```
Okay, speeding up your boot. Let me check what's slowing it down first...
```

## Configuration

Create `~/.config/reos/settings.toml`:

```toml
[reasoning]
enabled = true           # Enable planning system
auto_assess = true       # Automatically classify requests
always_confirm = false   # Ask before ANY system changes
explain_steps = true     # Show what each step does

[safety]
require_approval_for_permanent = true  # Confirm destructive ops
auto_backup_configs = true             # Backup before modifying
verify_each_step = true                # Check each step succeeded
rollback_on_failure = true             # Auto-undo on failure

[conversation]
verbosity = "normal"     # "minimal", "normal", or "detailed"
show_commands = true     # Show actual commands being run
```

## Usage

### Triggering Planning Manually

Even for simple requests, you can force planning:

```
You: plan: install docker
ReOS: Here's what I'll do to install Docker:
      1. Update package cache
      2. Install prerequisites
      3. Add Docker repository
      ...
```

### Checking Rollback History

```
You: what can you undo?
ReOS: Recent actions I can undo:
      1. Started nginx service (2 minutes ago)
      2. Installed vim package (5 minutes ago)
      Say 'undo' to revert the most recent action.
```

### Undoing Changes

```
You: undo
ReOS: Done! Undid: Started nginx service
      (ran: sudo systemctl stop nginx)
```

### Changing Verbosity

```
You: be more detailed
ReOS: Got it, I'll explain more about what I'm doing.

You: be brief
ReOS: Okay, keeping it short.
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ReasoningEngine                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────┐ │
│  │ Complexity   │────▶│ TaskPlanner  │────▶│ Executor    │ │
│  │ Assessor     │     │              │     │             │ │
│  └──────────────┘     └──────────────┘     └─────────────┘ │
│         │                    │                    │         │
│         ▼                    ▼                    ▼         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              ConversationManager                      │  │
│  │         (natural language formatting)                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                            │                                │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                   SafetyManager                       │  │
│  │    (backups, rollback stack, risk assessment)         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **ComplexityAssessor** | Fast classification using pattern matching |
| **TaskPlanner** | Breaks requests into steps with dependencies |
| **ExecutionEngine** | Runs steps with verification and rollback |
| **ConversationManager** | Formats output naturally |
| **SafetyManager** | Risk analysis, backups, rollback capability |

## Examples

### Simple Request (Direct Execution)

```
User: "show me disk space"
ReOS: [Complexity: simple, confidence: 0.9]
      [Executes: df -h]
      "You've got 120GB free on your main drive, 45GB on /home"
```

### Complex Request (Planning)

```
User: "my laptop's getting hot and the fan is loud"
ReOS: [Complexity: diagnostic]
      "Let me check what's using your CPU..."

      [Runs: top, sensors, systemd analysis]

      "Found it - Chrome has 8 processes using 340% CPU total.
       Also your CPU is at 87°C which is pretty hot.

       I can:
       1. Close Chrome tabs using the most CPU (saves the rest)
       2. Check if your fan vents are clear (I'll walk you through it)
       3. Set up better CPU thermal management

       What sounds good?"
```

### Risky Request (Approval Required)

```
User: "upgrade to the latest kernel"
ReOS: [Complexity: risky]
      "Kernel upgrade to 6.8.0. Here's what'll happen:

       1. Download ~200MB
       2. Install new kernel alongside current one (5.15.0)
       3. Update GRUB bootloader
       4. Reboot required

       Your current kernel stays installed as backup.
       If anything goes wrong, you can boot back to 5.15.0.

       Takes about 10 minutes. Ready?"

User: "yes"
ReOS: [Executes with progress updates]
      "All done! ✓
       New kernel installed. Reboot when you're ready.
       (I've backed up your boot config just in case)"
```

## Safety Guarantees

1. **Never execute risky operations without approval** - Destructive commands are always shown first
2. **Backups before modifications** - Config files are backed up automatically
3. **Rollback capability** - Most operations can be undone with a single command
4. **Transparent execution** - You always see what's being run
5. **Graceful failure** - If something breaks, changes are rolled back

## Limitations

- Planning uses heuristics and may misclassify edge cases
- Rollback is not always possible (e.g., deleted files without backup)
- Complex multi-system operations may need manual verification
- Learning system stores local data only (no cloud sync)

## Development

### Running Tests

```bash
PYTHONPATH=src uv run pytest tests/test_reasoning.py -v
```

### Adding New Task Templates

Templates for common operations are in `planner.py`:

```python
TASK_TEMPLATES = {
    "my_operation": {
        "pattern": r"do something with (\w+)",
        "steps": [
            {
                "id": "step1",
                "title": "First step",
                "step_type": StepType.COMMAND,
                "action": {"command": "echo {captured_group}"},
            },
        ],
    },
}
```

### Customizing Conversation Style

Subclass `ConversationManager` to change formatting:

```python
class MyConversationManager(ConversationManager):
    def format_plan_presentation(self, plan):
        # Custom formatting
        return my_custom_format(plan)
```

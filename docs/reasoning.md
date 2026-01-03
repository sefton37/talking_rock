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
┌─────────────────────────────────────────────────────────────────┐
│                      ReasoningEngine                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐     ┌──────────────┐     ┌─────────────────┐  │
│  │ Complexity   │────▶│ TaskPlanner  │────▶│ AdaptiveExecutor│  │
│  │ Assessor     │     │              │     │                 │  │
│  └──────────────┘     └──────────────┘     └────────┬────────┘  │
│         │                    │                      │            │
│         │                    │           ┌──────────┴─────────┐ │
│         │                    │           │  ErrorClassifier   │ │
│         │                    │           │  AdaptiveReplanner │ │
│         │                    │           │  ExecutionLearner  │ │
│         │                    │           └────────────────────┘ │
│         ▼                    ▼                    │              │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                ConversationManager                          │ │
│  │           (natural language formatting)                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                     SafetyManager                           │ │
│  │      (backups, rollback stack, risk assessment)             │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **ComplexityAssessor** | Fast classification using pattern matching |
| **TaskPlanner** | Breaks requests into steps with dependencies |
| **AdaptiveExecutor** | Runs steps with automatic error recovery |
| **ErrorClassifier** | Diagnoses failures (missing deps, permissions, etc.) |
| **AdaptiveReplanner** | Dynamically revises plans on failure |
| **ExecutionLearner** | Learns what works on this specific system |
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

## Adaptive Execution

When things go wrong during execution, ReOS doesn't just fail - it tries to fix the problem automatically.

### Error Classification

When a step fails, ReOS classifies the error into one of these categories:

| Category | Examples | Automatic Recovery |
|----------|----------|-------------------|
| **Missing Dependency** | "command not found", "package not installed" | Install the missing package |
| **Permission Denied** | "Permission denied", "must be root" | Retry with sudo |
| **Transient** | "Connection timed out", "Network unreachable" | Wait and retry |
| **Resource Busy** | "Device busy", "lock file exists" | Wait and retry |
| **Already Exists** | "File exists", "already installed" | Often fine, continue |
| **Not Found** | "No such file or directory" | Ask for help |
| **Conflict** | "Dependency conflict", "version mismatch" | Ask for help |

### Automatic Recovery Example

```
You: install and configure nginx

ReOS: [Starts executing plan...]

      Step 1: Installing nginx...
      ✗ Error: Unable to locate package nginx

      → Diagnosed: Missing dependency (apt cache outdated)
      → Trying fix: Updating package cache first...
      ✓ apt update completed

      → Retrying: Installing nginx...
      ✓ nginx installed

      Step 2: Enabling nginx service...
      ✓ Done

      Completed with 1 recovery action.
```

### Learning From Experience

ReOS remembers what works on your specific system:

- **Successful patterns** - Steps that worked are more likely to be used again
- **Failed patterns** - Steps that consistently fail get flagged
- **System quirks** - Platform-specific behaviors are recorded

This data is stored locally at `~/.config/reos/knowledge.db`.

```
You: why did you update apt first?

ReOS: I learned that on this system, apt install often fails
      without a recent cache update. I've seen this 3 times before,
      so now I do it proactively.
```

### Recovery Limits

For safety, automatic recovery is limited:
- Maximum 3 recovery attempts per execution
- Maximum 2 fix attempts per error type
- User intervention required for critical or unclassifiable errors

## Circuit Breakers (Paperclip Problem Prevention)

To prevent runaway AI behavior, ReOS enforces hard limits that **cannot be overridden by the AI**:

### Hard Limits

| Limit | Default | Purpose |
|-------|---------|---------|
| **Max Operations** | 25 | Stop after 25 commands per plan |
| **Max Time** | 5 minutes | Hard timeout for any plan execution |
| **Max Privilege Escalations** | 3 | Limit sudo additions |
| **Max Injected Steps** | 5 | Limit plan growth during recovery |
| **Human Checkpoint** | After 2 recoveries | Force human review |
| **Max Learned Patterns** | 1000 | Cap learning database size |

### Scope Drift Detection

ReOS blocks "fixes" that drift too far from the original request:

```
You: install nginx

ReOS: [During recovery, attempts to run rm -rf /var/log]
      ⛔ BLOCKED: Scope drift detected - Recursive deletion outside /tmp
      [Execution paused for human review]
```

Blocked patterns include:
- `rm -rf /` (outside /tmp)
- `chmod -R 777`
- `curl | bash` (unless requested)
- `fdisk`, `parted` (partition tools)
- Firewall disabling
- Credential modification

### What Happens When Limits Are Hit

When any limit is reached, execution **immediately stops** and returns control to you:

```
You: fix everything on my system

ReOS: [After 25 operations]
      ⚠️ Execution paused: Maximum operations reached (25/25)

      Completed: 24 steps
      Pending: 8 steps remaining
      Time elapsed: 2m 34s

      Continue? (This resets the operation counter)
```

### Why These Limits Exist

These limits prevent the AI from:
1. **Executing indefinitely** - No infinite loops
2. **Escalating privileges unbounded** - Can't keep adding sudo
3. **Growing plans without limit** - Can't inject infinite "fix" steps
4. **Consuming unlimited resources** - Memory and time are capped
5. **Drifting from the request** - Must stay related to what you asked

The limits are enforced in code and **cannot be modified by the AI during execution**. Only you can change them in config.

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

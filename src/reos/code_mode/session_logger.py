"""Session Logger - Comprehensive logging for Code Mode execution.

Provides detailed, structured logging of every step in Code Mode:
- LLM prompts and responses
- Decision points with reasoning
- Step execution with inputs/outputs
- Criterion evaluation with evidence

Logs are persisted to disk for post-mortem debugging.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LogEntry:
    """A single log entry with structured data."""

    timestamp: str
    level: str  # DEBUG, INFO, WARN, ERROR
    module: str  # intent, contract, executor, planner
    action: str  # llm_call, decision, step_start, step_complete, etc.
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.timestamp,
            "level": self.level,
            "module": self.module,
            "action": self.action,
            "msg": self.message,
            "data": self.data,
        }

    def to_line(self) -> str:
        """Format as a human-readable log line."""
        data_str = ""
        if self.data:
            # Truncate large values for readability
            truncated = {}
            for k, v in self.data.items():
                if isinstance(v, str) and len(v) > 200:
                    truncated[k] = v[:200] + f"... ({len(v)} chars)"
                elif isinstance(v, list) and len(v) > 5:
                    truncated[k] = v[:5] + [f"... ({len(v)} items)"]
                else:
                    truncated[k] = v
            data_str = f" | {json.dumps(truncated)}"
        return f"{self.timestamp} [{self.level}] {self.module}.{self.action}: {self.message}{data_str}"


class SessionLogger:
    """Comprehensive logger for a single Code Mode session.

    Creates a session-specific log file and provides methods for
    logging different types of events with structured data.

    Usage:
        logger = SessionLogger(session_id="abc123", prompt="build pacman")
        logger.log_llm_call("intent", "analyze_prompt", prompt_text, response_text)
        logger.log_decision("contract", "criterion_type", "chose TESTS_PASS because...")
        logger.log_step_start("executor", 1, "Create main.py")
        logger.close()
    """

    def __init__(
        self,
        session_id: str,
        prompt: str,
        log_dir: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.prompt = prompt
        self.started_at = datetime.now(timezone.utc)
        self.entries: list[LogEntry] = []

        # Set up log directory
        if log_dir is None:
            from ..settings import settings
            log_dir = settings.data_dir / "code_mode_sessions"
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create session log file
        timestamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"session_{timestamp}_{session_id[:8]}.log"
        self.json_file = self.log_dir / f"session_{timestamp}_{session_id[:8]}.json"

        # Write header
        self._write_line(f"=" * 80)
        self._write_line(f"Code Mode Session: {session_id}")
        self._write_line(f"Started: {self.started_at.isoformat()}")
        self._write_line(f"Prompt: {prompt}")
        self._write_line(f"=" * 80)
        self._write_line("")

        # Log session start
        self.log_info("session", "start", f"Session started: {prompt[:50]}...", {
            "session_id": session_id,
            "prompt": prompt,
        })

    def _now(self) -> str:
        """Get current timestamp string."""
        return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

    def _write_line(self, line: str) -> None:
        """Write a line to the log file."""
        try:
            with open(self.log_file, "a") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning("Failed to write to session log: %s", e)

    def _add_entry(self, entry: LogEntry) -> None:
        """Add entry to memory and write to file."""
        self.entries.append(entry)
        self._write_line(entry.to_line())

    def log_debug(self, module: str, action: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a debug-level entry."""
        self._add_entry(LogEntry(
            timestamp=self._now(),
            level="DEBUG",
            module=module,
            action=action,
            message=message,
            data=data or {},
        ))

    def log_info(self, module: str, action: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an info-level entry."""
        self._add_entry(LogEntry(
            timestamp=self._now(),
            level="INFO",
            module=module,
            action=action,
            message=message,
            data=data or {},
        ))

    def log_warn(self, module: str, action: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Log a warning-level entry."""
        self._add_entry(LogEntry(
            timestamp=self._now(),
            level="WARN",
            module=module,
            action=action,
            message=message,
            data=data or {},
        ))

    def log_error(self, module: str, action: str, message: str, data: dict[str, Any] | None = None) -> None:
        """Log an error-level entry."""
        self._add_entry(LogEntry(
            timestamp=self._now(),
            level="ERROR",
            module=module,
            action=action,
            message=message,
            data=data or {},
        ))

    # -------------------------------------------------------------------------
    # High-level logging methods
    # -------------------------------------------------------------------------

    def log_llm_call(
        self,
        module: str,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        response: str | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log an LLM call with full prompts and response."""
        self.log_debug(module, "llm_call_start", f"LLM call: {purpose}", {
            "purpose": purpose,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        })

        if response is not None:
            self.log_debug(module, "llm_call_response", f"LLM response ({len(response)} chars)", {
                "purpose": purpose,
                "response": response,
                "duration_ms": duration_ms,
            })

        if error is not None:
            self.log_error(module, "llm_call_error", f"LLM call failed: {error}", {
                "purpose": purpose,
                "error": error,
            })

    def log_decision(
        self,
        module: str,
        decision_type: str,
        choice: str,
        reason: str,
        alternatives: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        """Log a decision point with reasoning."""
        self.log_info(module, "decision", f"Decision: {decision_type} -> {choice}", {
            "decision_type": decision_type,
            "choice": choice,
            "reason": reason,
            "alternatives": alternatives or [],
            "evidence": evidence or {},
        })

    def log_step_start(
        self,
        step_num: int,
        total_steps: int,
        description: str,
        step_type: str | None = None,
        target_path: str | None = None,
    ) -> None:
        """Log the start of a plan step."""
        self.log_info("executor", "step_start", f"Step {step_num}/{total_steps}: {description}", {
            "step_num": step_num,
            "total_steps": total_steps,
            "description": description,
            "step_type": step_type,
            "target_path": target_path,
        })

    def log_step_complete(
        self,
        step_num: int,
        success: bool,
        output: str | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log step completion."""
        status = "SUCCESS" if success else "FAILED"
        self.log_info("executor", "step_complete", f"Step {step_num} {status}", {
            "step_num": step_num,
            "success": success,
            "output": output,
            "error": error,
            "duration_ms": duration_ms,
        })

    def log_code_generation(
        self,
        target_path: str,
        code: str,
        prompt_context: str | None = None,
    ) -> None:
        """Log generated code."""
        self.log_debug("executor", "code_generated", f"Generated code for {target_path} ({len(code)} chars)", {
            "target_path": target_path,
            "code": code,
            "code_lines": len(code.split("\n")),
            "prompt_context": prompt_context,
        })

    def log_command_execution(
        self,
        command: str,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Log a command execution."""
        status = f"exit={exit_code}" if exit_code is not None else "running"
        self.log_debug("executor", "command_exec", f"Command: {command[:50]}... ({status})", {
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": duration_ms,
        })

    def log_criterion_check(
        self,
        criterion_id: str,
        description: str,
        criterion_type: str,
        passed: bool,
        evidence: str | None = None,
        error: str | None = None,
    ) -> None:
        """Log a criterion verification."""
        status = "PASS" if passed else "FAIL"
        self.log_info("executor", "criterion_check", f"Criterion {status}: {description[:50]}...", {
            "criterion_id": criterion_id,
            "description": description,
            "criterion_type": criterion_type,
            "passed": passed,
            "evidence": evidence,
            "error": error,
        })

    def log_iteration_start(
        self,
        iteration: int,
        max_iterations: int,
        unfulfilled_count: int,
    ) -> None:
        """Log the start of an iteration."""
        self._write_line("")
        self._write_line(f"{'─' * 40}")
        self._write_line(f"ITERATION {iteration}/{max_iterations} - {unfulfilled_count} criteria remaining")
        self._write_line(f"{'─' * 40}")
        self.log_info("executor", "iteration_start", f"Iteration {iteration}/{max_iterations}", {
            "iteration": iteration,
            "max_iterations": max_iterations,
            "unfulfilled_count": unfulfilled_count,
        })

    def log_iteration_complete(
        self,
        iteration: int,
        fulfilled_count: int,
        total_criteria: int,
        duration_ms: float | None = None,
    ) -> None:
        """Log iteration completion."""
        self.log_info("executor", "iteration_complete", f"Iteration {iteration} complete: {fulfilled_count}/{total_criteria} criteria fulfilled", {
            "iteration": iteration,
            "fulfilled_count": fulfilled_count,
            "total_criteria": total_criteria,
            "duration_ms": duration_ms,
        })

    def log_phase_change(self, phase: str, description: str | None = None) -> None:
        """Log a phase transition."""
        self._write_line("")
        self._write_line(f">>> PHASE: {phase.upper()} {'- ' + description if description else ''}")
        self.log_info("executor", "phase_change", f"Phase: {phase}", {
            "phase": phase,
            "description": description,
        })

    def log_intent_discovered(
        self,
        goal: str,
        confidence: float,
        ambiguities: list[str],
        assumptions: list[str],
    ) -> None:
        """Log discovered intent."""
        self.log_info("intent", "discovered", f"Intent: {goal[:60]}... (confidence: {confidence:.0%})", {
            "goal": goal,
            "confidence": confidence,
            "ambiguities": ambiguities,
            "assumptions": assumptions,
        })

    def log_contract_built(
        self,
        contract_id: str,
        criteria_count: int,
        criteria_summaries: list[str],
    ) -> None:
        """Log contract creation."""
        self.log_info("contract", "built", f"Contract built with {criteria_count} criteria", {
            "contract_id": contract_id,
            "criteria_count": criteria_count,
            "criteria": criteria_summaries,
        })

    def log_plan_created(
        self,
        plan_id: str,
        step_count: int,
        step_summaries: list[str],
    ) -> None:
        """Log plan creation."""
        self.log_info("planner", "created", f"Plan created with {step_count} steps", {
            "plan_id": plan_id,
            "step_count": step_count,
            "steps": step_summaries,
        })

    def close(
        self,
        outcome: str,  # "completed", "failed", "cancelled"
        final_message: str | None = None,
    ) -> None:
        """Close the session and write final JSON."""
        ended_at = datetime.now(timezone.utc)
        duration = (ended_at - self.started_at).total_seconds()

        self._write_line("")
        self._write_line(f"=" * 80)
        self._write_line(f"Session {outcome.upper()}")
        self._write_line(f"Duration: {duration:.1f}s")
        if final_message:
            self._write_line(f"Message: {final_message}")
        self._write_line(f"=" * 80)

        self.log_info("session", "end", f"Session {outcome} after {duration:.1f}s", {
            "outcome": outcome,
            "duration_seconds": duration,
            "final_message": final_message,
            "entry_count": len(self.entries),
        })

        # Write JSON summary
        try:
            summary = {
                "session_id": self.session_id,
                "prompt": self.prompt,
                "started_at": self.started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_seconds": duration,
                "outcome": outcome,
                "entry_count": len(self.entries),
                "entries": [e.to_dict() for e in self.entries],
            }
            with open(self.json_file, "w") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            logger.warning("Failed to write session JSON: %s", e)

    def get_log_path(self) -> Path:
        """Get path to the log file."""
        return self.log_file

    def get_json_path(self) -> Path:
        """Get path to the JSON file."""
        return self.json_file


def list_sessions(log_dir: Path | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List recent Code Mode sessions.

    Returns:
        List of session summaries with paths and basic info.
    """
    if log_dir is None:
        from ..settings import settings
        log_dir = settings.data_dir / "code_mode_sessions"

    log_dir = Path(log_dir)
    if not log_dir.exists():
        return []

    sessions = []
    json_files = sorted(log_dir.glob("session_*.json"), reverse=True)[:limit]

    for json_file in json_files:
        try:
            with open(json_file) as f:
                data = json.load(f)
            sessions.append({
                "session_id": data.get("session_id"),
                "prompt": data.get("prompt", "")[:100],
                "started_at": data.get("started_at"),
                "duration_seconds": data.get("duration_seconds"),
                "outcome": data.get("outcome"),
                "entry_count": data.get("entry_count"),
                "log_file": str(json_file.with_suffix(".log")),
                "json_file": str(json_file),
            })
        except Exception as e:
            logger.warning("Failed to read session %s: %s", json_file, e)

    return sessions


def get_session_log(session_id: str, log_dir: Path | None = None) -> dict[str, Any] | None:
    """Get full session log by ID.

    Returns:
        Full session data including all entries, or None if not found.
    """
    if log_dir is None:
        from ..settings import settings
        log_dir = settings.data_dir / "code_mode_sessions"

    log_dir = Path(log_dir)
    if not log_dir.exists():
        return None

    # Find matching session
    for json_file in log_dir.glob("session_*.json"):
        try:
            with open(json_file) as f:
                data = json.load(f)
            if data.get("session_id", "").startswith(session_id):
                # Also include raw log content
                log_file = json_file.with_suffix(".log")
                if log_file.exists():
                    data["raw_log"] = log_file.read_text()
                return data
        except Exception:
            continue

    return None

"""Security module for ReOS.

Provides centralized security functions for:
- Input validation and sanitization
- Command escaping and safety checks
- Prompt injection detection
- Rate limiting for privileged operations
- Audit logging
"""

from __future__ import annotations

import logging
import re
import shlex
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Input Validation
# =============================================================================

# Safe patterns for common identifiers
SAFE_SERVICE_NAME = re.compile(r"^[a-zA-Z0-9_@.-]+$")
SAFE_CONTAINER_ID = re.compile(r"^[a-zA-Z0-9_.-]+$")
SAFE_PACKAGE_NAME = re.compile(r"^[a-zA-Z0-9_.+-]+$")
SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Maximum lengths to prevent buffer-based attacks
MAX_SERVICE_NAME_LEN = 256
MAX_CONTAINER_ID_LEN = 256
MAX_PACKAGE_NAME_LEN = 256
MAX_COMMAND_LEN = 4096


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field
        self.message = message


def validate_service_name(name: str) -> str:
    """Validate and return a safe service name.

    Args:
        name: The service name to validate

    Returns:
        The validated service name

    Raises:
        ValidationError: If the name is invalid
    """
    if not name:
        raise ValidationError("Service name cannot be empty", field="name")

    if len(name) > MAX_SERVICE_NAME_LEN:
        raise ValidationError(
            f"Service name too long (max {MAX_SERVICE_NAME_LEN} chars)",
            field="name",
        )

    if not SAFE_SERVICE_NAME.match(name):
        raise ValidationError(
            "Service name contains invalid characters. Only alphanumeric, underscore, dash, dot, and @ allowed",
            field="name",
        )

    # Block obvious injection attempts even if they pass regex
    dangerous_substrings = [";", "&", "|", "$", "`", "(", ")", "{", "}", "<", ">", "\n", "\r"]
    for char in dangerous_substrings:
        if char in name:
            raise ValidationError(
                f"Service name contains forbidden character: {repr(char)}",
                field="name",
            )

    return name


def validate_container_id(container_id: str) -> str:
    """Validate and return a safe container ID.

    Args:
        container_id: The container ID or name to validate

    Returns:
        The validated container ID

    Raises:
        ValidationError: If the ID is invalid
    """
    if not container_id:
        raise ValidationError("Container ID cannot be empty", field="container_id")

    if len(container_id) > MAX_CONTAINER_ID_LEN:
        raise ValidationError(
            f"Container ID too long (max {MAX_CONTAINER_ID_LEN} chars)",
            field="container_id",
        )

    if not SAFE_CONTAINER_ID.match(container_id):
        raise ValidationError(
            "Container ID contains invalid characters. Only alphanumeric, underscore, dash, and dot allowed",
            field="container_id",
        )

    return container_id


def validate_package_name(name: str) -> str:
    """Validate and return a safe package name.

    Args:
        name: The package name to validate

    Returns:
        The validated package name

    Raises:
        ValidationError: If the name is invalid
    """
    if not name:
        raise ValidationError("Package name cannot be empty", field="name")

    if len(name) > MAX_PACKAGE_NAME_LEN:
        raise ValidationError(
            f"Package name too long (max {MAX_PACKAGE_NAME_LEN} chars)",
            field="name",
        )

    if not SAFE_PACKAGE_NAME.match(name):
        raise ValidationError(
            "Package name contains invalid characters",
            field="name",
        )

    return name


def escape_shell_arg(arg: str) -> str:
    """Safely escape a string for use in shell commands.

    This should be used for ALL user-provided values interpolated into commands.

    Args:
        arg: The argument to escape

    Returns:
        Shell-escaped argument safe for interpolation
    """
    return shlex.quote(arg)


# =============================================================================
# Command Safety
# =============================================================================

# Patterns that indicate dangerous commands - more comprehensive than before
DANGEROUS_PATTERNS = [
    # Recursive deletions
    (r"\brm\b.*-[rR].*\s+/(?!\w)", "Recursive deletion of root or system paths"),
    (r"\brm\b.*--recursive.*\s+/(?!\w)", "Recursive deletion with long option"),
    (r"\brm\b.*-[rR]f.*\s+/(?:etc|var|usr|bin|sbin|lib|boot|home)\b", "Deletion of system directories"),

    # Disk destruction
    (r"\bdd\b.*\bof=/dev/[sh]d[a-z]", "Direct disk write"),
    (r"\bdd\b.*\bof=/dev/nvme", "Direct NVMe write"),
    (r"\bmkfs\b", "Filesystem creation"),
    (r"\bfdisk\b", "Partition manipulation"),
    (r"\bparted\b", "Partition manipulation"),

    # Fork bombs and resource exhaustion
    (r":\(\)\s*\{.*\}.*:\s*;", "Fork bomb detected"),
    (r"\bwhile\s+true.*do.*done", "Infinite loop"),

    # Privilege escalation attempts
    (r"\bchmod\b.*777\s+/", "Dangerous permission change on root"),
    (r"\bchmod\b.*-R.*777", "Recursive world-writable permissions"),
    (r"\bchown\b.*-R.*root.*:/", "Recursive ownership change to root"),

    # Network-based attacks
    (r"\bcurl\b.*\|\s*(?:ba)?sh", "Piping curl to shell"),
    (r"\bwget\b.*\|\s*(?:ba)?sh", "Piping wget to shell"),
    (r"\bcurl\b.*-o\s*/", "Curl writing to system paths"),

    # Credential theft
    (r"\bcat\b.*(?:/etc/shadow|/etc/passwd|\.ssh/)", "Reading sensitive files"),
    (r"\bcp\b.*(?:/etc/shadow|\.ssh/id_)", "Copying sensitive files"),

    # System state destruction
    (r"\bsystemctl\b.*(?:disable|mask).*(?:ssh|network|firewall)", "Disabling critical services"),
    (r"\bufw\b.*disable", "Disabling firewall"),
    (r"\biptables\b.*-F", "Flushing firewall rules"),
]

# Compile patterns for efficiency
_COMPILED_DANGEROUS = [(re.compile(p, re.IGNORECASE), msg) for p, msg in DANGEROUS_PATTERNS]


def is_command_dangerous(command: str) -> tuple[bool, str | None]:
    """Check if a command matches dangerous patterns.

    This is a defense-in-depth check - commands should also be escaped properly.

    Args:
        command: The command to check

    Returns:
        Tuple of (is_dangerous, reason_if_dangerous)
    """
    if len(command) > MAX_COMMAND_LEN:
        return True, f"Command too long (max {MAX_COMMAND_LEN} chars)"

    for pattern, message in _COMPILED_DANGEROUS:
        if pattern.search(command):
            logger.warning("Dangerous command blocked: %s - %s", message, command[:100])
            return True, message

    return False, None


def is_command_safe(command: str) -> tuple[bool, str | None]:
    """Check if a command is safe to execute.

    Combines multiple safety checks.

    Args:
        command: The command to check

    Returns:
        Tuple of (is_safe, warning_if_unsafe)
    """
    is_dangerous, reason = is_command_dangerous(command)
    if is_dangerous:
        return False, reason

    return True, None


# =============================================================================
# Prompt Injection Detection
# =============================================================================

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    # Direct instruction override
    (r"\bignore\b.*\b(?:previous|above|all)\b.*\b(?:instructions?|rules?|guidelines?)\b", "Instruction override attempt"),
    (r"\bdisregard\b.*\b(?:previous|above|all)\b", "Disregard instruction attempt"),
    (r"\bforget\b.*\b(?:everything|all|previous)\b", "Memory wipe attempt"),

    # Role manipulation
    (r"\byou\s+are\s+now\b", "Role change attempt"),
    (r"\bact\s+as\b.*\b(?:different|new|another)\b", "Role change attempt"),
    (r"\bpretend\s+(?:you're|to\s+be)\b", "Pretend instruction"),

    # System prompt extraction
    (r"\b(?:show|print|display|reveal)\b.*\b(?:system|initial)\b.*\b(?:prompt|instructions?)\b", "Prompt extraction attempt"),
    (r"\bwhat\s+(?:are|were)\s+your\s+(?:original|initial)\b", "Prompt extraction attempt"),

    # Jailbreak phrases
    (r"\bDAN\b", "Known jailbreak pattern"),
    (r"\bDo\s+Anything\s+Now\b", "Known jailbreak pattern"),
    (r"\bjailbreak\b", "Jailbreak attempt"),

    # Safety bypass
    (r"\bbypass\b.*\b(?:safety|security|filter)\b", "Safety bypass attempt"),
    (r"\b(?:don't|do\s+not)\s+(?:ask|require)\s+(?:for\s+)?(?:approval|confirmation|permission)\b", "Approval bypass attempt"),
    (r"\bwithout\b.*\b(?:asking|approval|confirmation)\b", "Approval bypass attempt"),

    # Hidden instructions
    (r"\[SYSTEM\]", "Fake system message"),
    (r"\[ADMIN\]", "Fake admin message"),
    (r"<\s*system\s*>", "Fake system tag"),
]

_COMPILED_INJECTION = [(re.compile(p, re.IGNORECASE), msg) for p, msg in INJECTION_PATTERNS]


@dataclass
class InjectionCheckResult:
    """Result of prompt injection detection."""

    is_suspicious: bool
    confidence: float  # 0.0 to 1.0
    detected_patterns: list[str] = field(default_factory=list)
    sanitized_input: str = ""


def detect_prompt_injection(user_input: str) -> InjectionCheckResult:
    """Detect potential prompt injection attempts.

    Args:
        user_input: The user's input to check

    Returns:
        InjectionCheckResult with detection details
    """
    detected = []

    for pattern, message in _COMPILED_INJECTION:
        if pattern.search(user_input):
            detected.append(message)
            logger.warning("Potential prompt injection: %s in: %s", message, user_input[:100])

    # Calculate confidence based on number of patterns matched
    confidence = min(1.0, len(detected) * 0.3) if detected else 0.0

    # Create sanitized version (strip obvious injection markers)
    sanitized = user_input
    for tag in ["[SYSTEM]", "[ADMIN]", "<system>", "</system>"]:
        sanitized = sanitized.replace(tag, "")

    return InjectionCheckResult(
        is_suspicious=len(detected) > 0,
        confidence=confidence,
        detected_patterns=detected,
        sanitized_input=sanitized.strip(),
    )


# =============================================================================
# Rate Limiting
# =============================================================================

class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after_seconds: float):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


@dataclass
class RateLimitConfig:
    """Configuration for a rate limiter."""

    max_requests: int  # Maximum requests allowed
    window_seconds: float  # Time window in seconds
    name: str = "default"  # Name for logging


class RateLimiter:
    """Token bucket rate limiter for privileged operations."""

    def __init__(self):
        # Track request timestamps per category
        self._requests: dict[str, list[float]] = defaultdict(list)

        # Default limits
        self._limits: dict[str, RateLimitConfig] = {
            # Authentication (strict to prevent brute force)
            "auth": RateLimitConfig(max_requests=5, window_seconds=60, name="login attempts"),
            # Privileged operations
            "sudo": RateLimitConfig(max_requests=10, window_seconds=60, name="sudo commands"),
            "service": RateLimitConfig(max_requests=20, window_seconds=60, name="service operations"),
            "container": RateLimitConfig(max_requests=30, window_seconds=60, name="container operations"),
            "package": RateLimitConfig(max_requests=5, window_seconds=300, name="package operations"),
            "approval": RateLimitConfig(max_requests=20, window_seconds=60, name="approval actions"),
        }

    def configure(self, category: str, max_requests: int, window_seconds: float) -> None:
        """Configure rate limit for a category."""
        self._limits[category] = RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
            name=category,
        )

    def check(self, category: str) -> None:
        """Check if request is allowed under rate limit.

        Args:
            category: The rate limit category to check

        Raises:
            RateLimitExceeded: If the rate limit is exceeded
        """
        if category not in self._limits:
            return  # No limit configured

        config = self._limits[category]
        now = time.time()
        window_start = now - config.window_seconds

        # Clean old entries and get current count
        self._requests[category] = [
            t for t in self._requests[category] if t > window_start
        ]

        if len(self._requests[category]) >= config.max_requests:
            oldest = min(self._requests[category])
            retry_after = oldest + config.window_seconds - now
            logger.warning(
                "Rate limit exceeded for %s: %d/%d in %.0fs",
                config.name,
                len(self._requests[category]),
                config.max_requests,
                config.window_seconds,
            )
            raise RateLimitExceeded(
                f"Rate limit exceeded for {config.name}. "
                f"Max {config.max_requests} requests per {config.window_seconds:.0f}s",
                retry_after_seconds=max(0, retry_after),
            )

        # Record this request
        self._requests[category].append(now)

    def get_remaining(self, category: str) -> tuple[int, float]:
        """Get remaining requests and reset time for a category.

        Returns:
            Tuple of (remaining_requests, seconds_until_reset)
        """
        if category not in self._limits:
            return 999, 0

        config = self._limits[category]
        now = time.time()
        window_start = now - config.window_seconds

        # Clean old entries
        self._requests[category] = [
            t for t in self._requests[category] if t > window_start
        ]

        remaining = config.max_requests - len(self._requests[category])

        if self._requests[category]:
            oldest = min(self._requests[category])
            reset_in = oldest + config.window_seconds - now
        else:
            reset_in = config.window_seconds

        return remaining, max(0, reset_in)


# Global rate limiter instance
_rate_limiter = RateLimiter()


def check_rate_limit(category: str) -> None:
    """Check rate limit for a category (convenience function)."""
    _rate_limiter.check(category)


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    return _rate_limiter


# =============================================================================
# Audit Logging
# =============================================================================

class AuditEventType(Enum):
    """Types of security-relevant events."""

    # Authentication events
    AUTH_LOGIN_SUCCESS = "auth_login_success"
    AUTH_LOGIN_FAILED = "auth_login_failed"
    AUTH_LOGOUT = "auth_logout"
    AUTH_SESSION_EXPIRED = "auth_session_expired"

    # Command execution events
    COMMAND_EXECUTED = "command_executed"
    COMMAND_BLOCKED = "command_blocked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_EDITED = "approval_edited"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INJECTION_DETECTED = "injection_detected"
    VALIDATION_FAILED = "validation_failed"
    SUDO_USED = "sudo_used"


@dataclass
class AuditEvent:
    """A security audit event."""

    event_type: AuditEventType
    timestamp: datetime
    details: dict[str, Any]
    user: str = "local"
    session_id: str | None = None
    success: bool = True


class SecurityAuditor:
    """Audit logger for security-relevant events."""

    def __init__(self, db: Any = None):
        """Initialize the auditor.

        Args:
            db: Database instance for persistent logging (optional)
        """
        self._db = db
        self._events: list[AuditEvent] = []
        self._max_memory_events = 1000

    def log(
        self,
        event_type: AuditEventType,
        details: dict[str, Any],
        user: str = "local",
        session_id: str | None = None,
        success: bool = True,
    ) -> None:
        """Log a security event.

        Args:
            event_type: Type of event
            details: Event details
            user: User who triggered the event
            session_id: Associated session ID
            success: Whether the operation succeeded
        """
        event = AuditEvent(
            event_type=event_type,
            timestamp=datetime.now(),
            details=details,
            user=user,
            session_id=session_id,
            success=success,
        )

        # Log to file
        logger.info(
            "AUDIT: %s | user=%s | success=%s | %s",
            event_type.value,
            user,
            success,
            details,
        )

        # Keep in memory (bounded)
        self._events.append(event)
        if len(self._events) > self._max_memory_events:
            self._events = self._events[-self._max_memory_events:]

        # Persist to database if available
        if self._db is not None:
            try:
                self._persist_event(event)
            except Exception as e:
                logger.error("Failed to persist audit event: %s", e)

    def _persist_event(self, event: AuditEvent) -> None:
        """Persist event to database."""
        if hasattr(self._db, "insert_audit_event"):
            self._db.insert_audit_event(
                event_type=event.event_type.value,
                timestamp=event.timestamp.isoformat(),
                details=event.details,
                user=event.user,
                session_id=event.session_id,
                success=event.success,
            )

    def get_recent_events(
        self,
        limit: int = 100,
        event_type: AuditEventType | None = None,
    ) -> list[AuditEvent]:
        """Get recent audit events.

        Args:
            limit: Maximum events to return
            event_type: Filter by event type

        Returns:
            List of recent events
        """
        events = self._events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events[-limit:]

    def log_command_execution(
        self,
        command: str,
        success: bool,
        return_code: int,
        approval_id: str | None = None,
        edited: bool = False,
    ) -> None:
        """Convenience method for logging command execution."""
        self.log(
            event_type=AuditEventType.COMMAND_EXECUTED,
            details={
                "command": command[:500],  # Truncate for storage
                "return_code": return_code,
                "approval_id": approval_id,
                "edited": edited,
                "has_sudo": "sudo " in command,
            },
            success=success,
        )

        # Also log sudo usage separately if present
        if "sudo " in command:
            self.log(
                event_type=AuditEventType.SUDO_USED,
                details={
                    "command": command[:500],
                    "approval_id": approval_id,
                },
                success=success,
            )


# Global auditor instance (initialized without DB, can be configured later)
_auditor = SecurityAuditor()


def get_auditor() -> SecurityAuditor:
    """Get the global security auditor."""
    return _auditor


def configure_auditor(db: Any) -> None:
    """Configure the global auditor with a database."""
    global _auditor
    _auditor = SecurityAuditor(db)


def audit_log(
    event_type: AuditEventType,
    details: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Log an audit event (convenience function)."""
    _auditor.log(event_type, details, **kwargs)

"""Shell Context Gathering for Parse Gate.

This module implements context-aware command proposal by gathering
system state before asking the LLM to propose a command.

Kernel Principle: "If you can't verify it, decompose it." (RIVA)

The context layer:
1. Analyzes intent (run/install/service verbs)
2. Gathers relevant context (PATH, packages, services)
3. Enriches the LLM prompt with system knowledge
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reos.system_state import SteadyState

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Intent Pattern Matching
# ═══════════════════════════════════════════════════════════════════════════════

INTENT_PATTERNS: dict[str, list[str]] = {
    "run": ["run", "launch", "open", "execute", "fire up", "start up"],
    "install": ["install", "add", "get", "download", "set up", "setup"],
    "remove": ["remove", "uninstall", "delete", "purge", "get rid of"],
    "service_start": ["start", "restart", "reload"],
    "service_stop": ["stop", "kill", "terminate"],
    "service_config": ["enable", "disable"],
    "update": ["update", "upgrade", "refresh"],
    "check": ["check", "status", "is running", "show"],
}

# Words that indicate the target is a service, not a program
SERVICE_INDICATORS = ["service", "daemon", "server"]

# Common package name mappings (natural language → package name)
PACKAGE_ALIASES: dict[str, str] = {
    "chrome": "google-chrome-stable",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "python": "python3",
    "node": "nodejs",
    "java": "default-jdk",
    "postgres": "postgresql",
    "mysql": "mysql-server",
    "mongo": "mongodb",
    "redis": "redis-server",
}


@dataclass
class ShellContext:
    """Context gathered before proposing a command."""

    # Intent analysis
    intent_verb: str | None = None          # "run", "install", "service_start", etc.
    intent_target: str | None = None        # "gimp", "nginx", etc.
    original_input: str = ""                # The raw natural language input

    # Executable context
    executable_path: str | None = None      # Result of `which <target>`

    # Package context
    package_installed: bool = False         # Is it in installed packages?
    package_version: str | None = None      # Version if installed
    package_available: bool = False         # Is it available in apt cache?
    package_description: str | None = None  # Package description

    # Service context
    is_service: bool = False                # Is it a systemd service?
    service_status: str | None = None       # "active", "inactive", "failed"
    service_enabled: bool = False           # Is it enabled at boot?

    # FTS5 search results (for semantic matching)
    fts_matches: list[dict[str, str]] = field(default_factory=list)  # Matching packages/apps

    # Decision
    can_verify: bool = False                # Do we have enough context?

    def to_context_string(self) -> str:
        """Format context for LLM prompt."""
        lines = []

        if self.intent_target:
            # Executable info
            if self.executable_path:
                lines.append(f"- {self.intent_target}: executable at {self.executable_path}")
            elif self.package_installed:
                version = f" (v{self.package_version})" if self.package_version else ""
                lines.append(f"- {self.intent_target}: package installed{version}")
            elif self.package_available:
                lines.append(f"- {self.intent_target}: package available but NOT installed")
                if self.package_description:
                    lines.append(f"  Description: {self.package_description}")
            elif self.fts_matches:
                # Show FTS5 search results when exact match not found
                lines.append(f"- {self.intent_target}: NOT FOUND directly, but similar programs found:")
                for match in self.fts_matches[:3]:  # Top 3 matches
                    name = match.get("name", match.get("desktop_id", "unknown"))
                    desc = match.get("description", match.get("comment", ""))
                    if desc:
                        lines.append(f"  • {name}: {desc}")
                    else:
                        lines.append(f"  • {name}")
            else:
                lines.append(f"- {self.intent_target}: NOT FOUND in PATH or packages")

            # Service info
            if self.is_service:
                status = self.service_status or "unknown"
                enabled = "enabled" if self.service_enabled else "disabled"
                lines.append(f"- {self.intent_target} service: {status}, {enabled} at boot")

        return "\n".join(lines) if lines else "No additional context available."


class ShellContextGatherer:
    """Gathers system context for natural language commands.

    Uses a hierarchy of lookups:
    1. Exact match in PATH (which)
    2. Package status (dpkg -s)
    3. Package availability (apt-cache)
    4. Service status (systemctl)
    """

    def __init__(self, steady_state: SteadyState | None = None):
        """Initialize with optional steady state cache.

        Args:
            steady_state: Cached system state from SteadyStateCollector
        """
        self.steady_state = steady_state
        self._package_manager = self._detect_package_manager()

    def _detect_package_manager(self) -> str:
        """Detect the system's package manager."""
        if self.steady_state:
            return self.steady_state.package_manager

        # Check common package managers
        if shutil.which("apt"):
            return "apt"
        elif shutil.which("dnf"):
            return "dnf"
        elif shutil.which("pacman"):
            return "pacman"
        elif shutil.which("zypper"):
            return "zypper"
        return "unknown"

    def analyze_intent(self, natural_language: str) -> tuple[str | None, str | None]:
        """Extract action verb and target from natural language input.

        Args:
            natural_language: The user's request (e.g., "run gimp", "install nodejs")

        Returns:
            Tuple of (intent_verb, intent_target)
            - intent_verb: One of the INTENT_PATTERNS keys or None
            - intent_target: The program/package/service name or None
        """
        text = natural_language.lower().strip()
        words = text.split()

        if not words:
            return None, None

        intent_verb = None
        target_start_idx = 0

        # Find the intent verb
        for verb_type, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                pattern_words = pattern.split()
                pattern_len = len(pattern_words)

                # Check if the text starts with this pattern
                if words[:pattern_len] == pattern_words:
                    intent_verb = verb_type
                    target_start_idx = pattern_len
                    break

                # Also check if pattern appears anywhere (for "can you run X")
                for i, word in enumerate(words):
                    if words[i:i + pattern_len] == pattern_words:
                        intent_verb = verb_type
                        target_start_idx = i + pattern_len
                        break

            if intent_verb:
                break

        # Extract target (everything after the verb, cleaned up)
        if target_start_idx < len(words):
            target_words = words[target_start_idx:]
            # Remove common filler words
            target_words = [w for w in target_words if w not in
                           ["the", "a", "an", "my", "please", "for", "me"]]
            if target_words:
                target = " ".join(target_words)
                # Check for aliases (both multi-word and single-word)
                target = PACKAGE_ALIASES.get(target, target)
                # Also check single word alias if not already resolved
                if len(target_words) == 1:
                    target = PACKAGE_ALIASES.get(target_words[0], target)
                return intent_verb, target

        return intent_verb, None

    def gather_context(
        self,
        intent_verb: str | None,
        intent_target: str | None,
        original_input: str = ""
    ) -> ShellContext:
        """Gather all relevant context for the target.

        Args:
            intent_verb: The detected intent (run, install, etc.)
            intent_target: The target program/package/service
            original_input: The original natural language input

        Returns:
            ShellContext with gathered information
        """
        context = ShellContext(
            intent_verb=intent_verb,
            intent_target=intent_target,
            original_input=original_input,
        )

        if not intent_target:
            return context

        # Level 1: Check PATH (fastest)
        context.executable_path = self.check_executable(intent_target)

        # Level 2: Check if package is installed
        installed, version = self.check_package_installed(intent_target)
        context.package_installed = installed
        context.package_version = version

        # Level 3: Check if package is available
        if not installed:
            available, description = self.check_package_available(intent_target)
            context.package_available = available
            context.package_description = description

        # Level 4: Check if it's a service
        is_service, status, enabled = self.check_service(intent_target)
        context.is_service = is_service
        context.service_status = status
        context.service_enabled = enabled

        # Level 5: FTS5 search (semantic matching when exact match fails)
        if not (context.executable_path or context.package_installed or
                context.package_available or context.is_service):
            # Try semantic search using FTS5
            fts_matches = self.search_fts5(original_input or intent_target)
            context.fts_matches = fts_matches

        # Determine if we can verify
        context.can_verify = bool(
            context.executable_path or
            context.package_installed or
            context.package_available or
            context.is_service or
            context.fts_matches  # FTS5 matches also count as verifiable
        )

        return context

    def check_executable(self, target: str) -> str | None:
        """Check if target is an executable in PATH.

        Args:
            target: Program name to check

        Returns:
            Full path to executable or None
        """
        try:
            result = subprocess.run(
                ["which", target],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def check_package_installed(self, target: str) -> tuple[bool, str | None]:
        """Check if package is installed.

        Args:
            target: Package name to check

        Returns:
            Tuple of (is_installed, version)
        """
        # First check steady state cache
        if self.steady_state and target in self.steady_state.key_packages:
            return True, self.steady_state.key_packages[target]

        # Then check dpkg (Debian/Ubuntu)
        if self._package_manager in ("apt", "unknown"):
            try:
                result = subprocess.run(
                    ["dpkg", "-s", target],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    # Extract version
                    for line in result.stdout.split("\n"):
                        if line.startswith("Version:"):
                            return True, line.split(":", 1)[1].strip()
                    return True, None
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        # Check rpm (Fedora/RHEL)
        elif self._package_manager == "dnf":
            try:
                result = subprocess.run(
                    ["rpm", "-q", target],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0:
                    return True, result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return False, None

    def check_package_available(self, target: str) -> tuple[bool, str | None]:
        """Check if package is available in repositories.

        Args:
            target: Package name to check

        Returns:
            Tuple of (is_available, description)
        """
        if self._package_manager in ("apt", "unknown"):
            try:
                result = subprocess.run(
                    ["apt-cache", "show", target],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    # Extract description
                    for line in result.stdout.split("\n"):
                        if line.startswith("Description:"):
                            return True, line.split(":", 1)[1].strip()
                    return True, None
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        elif self._package_manager == "dnf":
            try:
                result = subprocess.run(
                    ["dnf", "info", target],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True, None
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return False, None

    def check_service(self, target: str) -> tuple[bool, str | None, bool]:
        """Check if target is a systemd service.

        Args:
            target: Service name to check

        Returns:
            Tuple of (is_service, status, is_enabled)
        """
        # First check steady state cache
        if self.steady_state:
            if target in self.steady_state.enabled_services:
                return True, None, True
            if target in self.steady_state.available_services:
                return True, None, False

        # Check systemctl - first verify the service exists using 'show'
        service_names = [target, f"{target}.service"]

        for service_name in service_names:
            try:
                # Use 'systemctl show' to verify service exists
                # It returns LoadState=loaded for real services, LoadState=not-found for fake ones
                show_result = subprocess.run(
                    ["systemctl", "show", service_name, "--property=LoadState"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                load_state = show_result.stdout.strip()

                # Only continue if the service actually exists
                if "LoadState=not-found" in load_state or "LoadState=masked" in load_state:
                    continue

                if "LoadState=loaded" not in load_state:
                    continue

                # Now get the status
                result = subprocess.run(
                    ["systemctl", "is-active", service_name],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                status = result.stdout.strip()

                # Check if enabled
                enabled_result = subprocess.run(
                    ["systemctl", "is-enabled", service_name],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                is_enabled = enabled_result.returncode == 0

                # If we got a status, it's a valid service
                if status in ("active", "inactive", "failed", "activating", "deactivating"):
                    return True, status, is_enabled

            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return False, None, False

    def search_fts5(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        """Search packages and desktop apps using hybrid search.

        Uses FTS5 for fast keyword matching, with semantic vector
        similarity as fallback for synonym matching.

        Args:
            query: Search query (e.g., "image editor", "picture editor")
            limit: Maximum results to return

        Returns:
            List of matching packages/apps with name and description
        """
        if not query or not query.strip():
            return []

        try:
            from .db import get_db
            from .system_index import SystemIndexer

            db = get_db()
            indexer = SystemIndexer(db)

            # Use hybrid search (FTS5 first, semantic fallback)
            results = indexer.search_hybrid(query, limit=limit)

            # Convert to expected format
            combined: list[dict[str, str]] = []
            for item in results:
                combined.append({
                    "name": item["name"],
                    "description": item.get("description", ""),
                    "type": item.get("source", "package"),
                    "match_type": item.get("match_type", "keyword"),
                })

            return combined[:limit]
        except Exception as e:
            logger.debug("FTS5 search failed: %s", e)
            return []


def get_context_for_proposal(natural_language: str) -> ShellContext:
    """Convenience function to gather context for a natural language command.

    Args:
        natural_language: The user's request

    Returns:
        ShellContext with gathered information
    """
    # Try to use cached steady state
    try:
        from reos.system_state import SteadyStateCollector
        collector = SteadyStateCollector()
        steady_state = collector.refresh_if_stale(max_age_seconds=3600)
    except Exception:
        steady_state = None

    gatherer = ShellContextGatherer(steady_state=steady_state)
    intent_verb, intent_target = gatherer.analyze_intent(natural_language)

    return gatherer.gather_context(
        intent_verb=intent_verb,
        intent_target=intent_target,
        original_input=natural_language,
    )

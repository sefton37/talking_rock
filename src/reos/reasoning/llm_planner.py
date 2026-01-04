"""LLM-based planning for ReOS reasoning system.

Uses local Ollama LLM to understand user intent and generate
goal-oriented plans. This replaces rigid regex pattern matching
with intelligent interpretation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..ollama import OllamaClient, OllamaError

logger = logging.getLogger(__name__)


@dataclass
class ParsedIntent:
    """Structured intent parsed from user request."""

    action: str  # e.g., "remove", "stop", "restart", "install"
    resource_type: str  # e.g., "container", "service", "package", "file"
    targets: list[str]  # Specific targets or filters
    conditions: dict[str, Any]  # e.g., {"state": "running", "name_contains": "nextcloud"}
    confidence: float
    explanation: str


@dataclass
class PlanStep:
    """A step in the generated plan."""

    title: str
    description: str
    tool: str
    tool_args: dict[str, Any]
    risk_level: str  # "safe", "low", "medium", "high"
    rollback_command: str | None = None
    depends_on: list[str] | None = None


class LLMPlanner:
    """LLM-powered planning for understanding intent and generating plans.

    Uses local Ollama to:
    1. Parse user intent from natural language
    2. Match targets against system context
    3. Generate actionable steps to accomplish goals
    """

    def __init__(self, ollama: OllamaClient | None = None) -> None:
        """Initialize the LLM planner.

        Args:
            ollama: OllamaClient instance. If None, creates default.
        """
        self._ollama = ollama

    def _get_ollama(self) -> OllamaClient:
        """Get or create Ollama client."""
        if self._ollama is None:
            self._ollama = OllamaClient()
        return self._ollama

    def parse_intent(
        self,
        request: str,
        system_context: dict[str, Any] | None = None,
    ) -> ParsedIntent:
        """Parse user intent from natural language request.

        Uses LLM to understand what the user wants to accomplish.

        Args:
            request: Natural language request from user
            system_context: Available system resources (containers, services, etc.)

        Returns:
            ParsedIntent with structured understanding of the request
        """
        context = system_context or {}

        # Build context description for LLM
        context_desc = self._format_context_for_llm(context)

        system_prompt = """You are an intent parser for a Linux system administration tool.
Your job is to understand what the user wants to accomplish and extract structured intent.

CRITICAL DISTINCTION - Query vs Action:
- QUERY: User is asking a question, wanting information (list, show, what, check status)
  → action should be "query" - NO plan needed, just answer the question
- ACTION: User wants to CHANGE something (stop, remove, install, restart, delete, kill)
  → action should be the specific action - plan IS needed

CRITICAL: You will be given the ACTUAL system state (running containers, services, packages).
Use this to match user references to REAL resources.

Parse the user's request and return a JSON object with:
{
    "action": "query" for questions, OR specific action (stop, remove, install, restart, etc.),
    "resource_type": "what type of resource (container, service, package, file, process, etc.)",
    "targets": ["ACTUAL resource names from system context that match"],
    "conditions": {"optional conditions"},
    "confidence": 0.0-1.0,
    "explanation": "what you understood"
}

EXAMPLES - Queries (action="query", no plan needed):
- "what containers are running?" -> {"action": "query", "resource_type": "container", "targets": [], "conditions": {}, "confidence": 0.95, "explanation": "User wants to see running containers"}
- "is nextcloud running?" -> {"action": "query", "resource_type": "container", "targets": ["nextcloud"], "conditions": {}, "confidence": 0.9, "explanation": "User asking about nextcloud status"}
- "list my services" -> {"action": "query", "resource_type": "service", "targets": [], "conditions": {}, "confidence": 0.95, "explanation": "User wants to list services"}

EXAMPLES - Actions (specific action, plan needed):
- "stop and remove nextcloud containers" -> {"action": "stop_and_remove", "resource_type": "container", "targets": ["nextcloud-app", "nextcloud-redis"], "conditions": {}, "confidence": 0.95, "explanation": "Stop and remove containers matching nextcloud"}
- "remove the redis container" -> {"action": "remove", "resource_type": "container", "targets": ["nextcloud-redis"], "conditions": {}, "confidence": 0.9, "explanation": "Remove container containing redis"}
- "restart nginx" -> {"action": "restart", "resource_type": "service", "targets": ["nginx.service"], "conditions": {}, "confidence": 0.9, "explanation": "Restart nginx service"}
- "install htop" -> {"action": "install", "resource_type": "package", "targets": ["htop"], "conditions": {}, "confidence": 0.95, "explanation": "Install htop package"}

COMBINED REQUESTS (query + action):
- "what containers are running, stop the nextcloud ones" -> {"action": "stop", "resource_type": "container", "targets": ["nextcloud-app", "nextcloud-redis"], "conditions": {}, "confidence": 0.9, "explanation": "User wants to stop nextcloud containers after viewing"}
- "is nextcloud running? if so remove it" -> {"action": "remove", "resource_type": "container", "targets": ["nextcloud-app", "nextcloud-redis"], "conditions": {"if_running": true}, "confidence": 0.85, "explanation": "Remove nextcloud containers if running"}

IMPORTANT:
- Return valid JSON only
- Use EXACT resource names from the system context
- For combined query+action requests, prioritize the ACTION
- If request mentions "if so", "then", "want to" with an action, it's an ACTION request"""

        user_prompt = f"""Parse this request:
"{request}"

Available system context:
{context_desc}

Return the structured intent as JSON:"""

        try:
            ollama = self._get_ollama()
            response = ollama.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.1,  # Low temperature for consistent parsing
                timeout_seconds=30.0,
            )

            data = json.loads(response)
            return ParsedIntent(
                action=data.get("action", "unknown"),
                resource_type=data.get("resource_type", "unknown"),
                targets=data.get("targets", []),
                conditions=data.get("conditions", {}),
                confidence=data.get("confidence", 0.5),
                explanation=data.get("explanation", ""),
            )

        except (OllamaError, json.JSONDecodeError) as e:
            logger.warning("LLM intent parsing failed: %s", e)
            # Return low-confidence fallback
            return ParsedIntent(
                action="unknown",
                resource_type="unknown",
                targets=[],
                conditions={},
                confidence=0.1,
                explanation=f"Failed to parse: {e}",
            )

    def generate_plan(
        self,
        intent: ParsedIntent,
        system_context: dict[str, Any] | None = None,
    ) -> list[PlanStep]:
        """Generate an actionable plan to accomplish the parsed intent.

        Uses LLM to create steps that achieve the user's goal.

        Args:
            intent: Parsed intent from parse_intent()
            system_context: System resources for matching targets

        Returns:
            List of PlanStep objects
        """
        context = system_context or {}

        # Match targets against actual system resources
        matched_resources = self._match_targets(intent, context)

        system_prompt = """You are a Linux system administration planner.
Given a user's intent and matched system resources, generate a step-by-step plan.

CRITICAL RULES:
1. Return a JSON ARRAY of steps (not a single object!)
2. Use the EXACT resource names from the matched resources
3. Create SEPARATE steps for each resource and each action

JSON format - MUST be an array:
[
    {"title": "Step 1", "description": "...", "tool": "linux_run_command", "tool_args": {"command": "..."}, "risk_level": "medium"},
    {"title": "Step 2", "description": "...", "tool": "linux_run_command", "tool_args": {"command": "..."}, "risk_level": "high"}
]

For combined actions like "stop_and_remove":
- Create SEPARATE steps: first stop, then remove
- One step per container/resource

Example for "stop_and_remove containers [nextcloud-app, nextcloud-redis]":
[
    {"title": "Stop nextcloud-app", "tool": "linux_run_command", "tool_args": {"command": "docker stop nextcloud-app"}, "risk_level": "medium"},
    {"title": "Remove nextcloud-app", "tool": "linux_run_command", "tool_args": {"command": "docker rm nextcloud-app"}, "risk_level": "high", "depends_on": ["Stop nextcloud-app"]},
    {"title": "Stop nextcloud-redis", "tool": "linux_run_command", "tool_args": {"command": "docker stop nextcloud-redis"}, "risk_level": "medium"},
    {"title": "Remove nextcloud-redis", "tool": "linux_run_command", "tool_args": {"command": "docker rm nextcloud-redis"}, "risk_level": "high", "depends_on": ["Stop nextcloud-redis"]}
]

Available tools:
- linux_run_command: Execute shell commands. Args: {"command": "..."}

Risk levels:
- "high": destructive (rm, remove, delete)
- "medium": state-changing (stop, restart)
- "safe": read-only

IMPORTANT: Always return a JSON ARRAY [], never a single object {}."""

        # Build description of what we're trying to do
        # Use MATCHED resources only, not the original targets (which may be fuzzy)
        matched_desc = self._format_matched_resources(matched_resources)

        # Get the actual list of resources to operate on
        if intent.resource_type == "container":
            actual_targets = matched_resources.get("containers", [])
        elif intent.resource_type == "service":
            actual_targets = matched_resources.get("services", [])
        elif intent.resource_type == "package":
            actual_targets = matched_resources.get("packages", intent.targets)
        else:
            actual_targets = intent.targets

        logger.info("Plan generation: action=%s, matched_targets=%s", intent.action, actual_targets)

        user_prompt = f"""Generate a plan for this intent:

Action: {intent.action}
Resource type: {intent.resource_type}

ACTUAL RESOURCES TO OPERATE ON (use these exact names):
{actual_targets}

Create steps for EACH resource listed above.
For action "{intent.action}", create the appropriate steps for each one.

Return the step-by-step plan as JSON array:"""

        try:
            ollama = self._get_ollama()
            response = ollama.chat_json(
                system=system_prompt,
                user=user_prompt,
                temperature=0.2,
                timeout_seconds=45.0,
            )

            steps_data = json.loads(response)

            # Handle various ways LLM might return steps
            if isinstance(steps_data, dict):
                # Try common wrapper keys first
                for key in ("steps", "plan", "actions", "tasks"):
                    if key in steps_data and isinstance(steps_data[key], list):
                        steps_data = steps_data[key]
                        break
                else:
                    # Check if dict looks like a single step (has tool or title)
                    if "tool" in steps_data or "title" in steps_data:
                        logger.debug("LLM returned single step dict, wrapping in list")
                        steps_data = [steps_data]
                    else:
                        logger.warning("LLM returned dict without steps list: keys=%s", list(steps_data.keys()))
                        return []

            if not isinstance(steps_data, list):
                logger.warning("LLM returned non-list plan: %s", type(steps_data))
                return []

            steps = []
            for step in steps_data:
                steps.append(PlanStep(
                    title=step.get("title", "Untitled step"),
                    description=step.get("description", ""),
                    tool=step.get("tool", "linux_run_command"),
                    tool_args=step.get("tool_args", {}),
                    risk_level=step.get("risk_level", "medium"),
                    rollback_command=step.get("rollback_command"),
                    depends_on=step.get("depends_on"),
                ))
            return steps

        except (OllamaError, json.JSONDecodeError) as e:
            logger.warning("LLM plan generation failed: %s", e)
            return []

    def _format_context_for_llm(self, context: dict[str, Any]) -> str:
        """Format system context for LLM consumption.

        Provides comprehensive system state so the LLM can:
        - Match user references to actual resources
        - Understand what's running vs stopped
        - Know exact names for commands
        """
        parts = []

        if context.get("hostname"):
            parts.append(f"Hostname: {context['hostname']}")

        if context.get("package_manager"):
            parts.append(f"Package manager: {context['package_manager']}")

        # Containers with full details
        containers = context.get("containers", {})
        if containers:
            all_containers = containers.get("all", [])
            if all_containers:
                parts.append("\nDOCKER CONTAINERS:")
                for c in all_containers:
                    name = c.get("name", c.get("id", "unknown"))
                    image = c.get("image", "")
                    status = c.get("status", "")
                    state = "running" if status.lower().startswith("up") else "stopped"
                    parts.append(f"  - {name} ({image}) [{state}]")
            elif context.get("container_names"):
                # Fallback to names only
                parts.append(f"\nContainers: {', '.join(context['container_names'])}")

        # Services with status
        services = context.get("services", [])
        if services:
            running = [s for s in services if s.get("active")]
            if running:
                parts.append(f"\nRUNNING SERVICES ({len(running)} total):")
                # Show first 30 services to avoid overwhelming context
                for s in running[:30]:
                    name = s.get("name", "")
                    desc = s.get("description", "")[:50]
                    parts.append(f"  - {name}: {desc}")
                if len(running) > 30:
                    parts.append(f"  ... and {len(running) - 30} more")
        elif context.get("service_names"):
            # Fallback to names only
            names = context["service_names"][:30]
            parts.append(f"\nServices: {', '.join(names)}")
            if len(context["service_names"]) > 30:
                parts.append(f"  ... and {len(context['service_names']) - 30} more")

        # Installed packages (summary)
        if context.get("installed_packages"):
            packages = context["installed_packages"]
            parts.append(f"\nInstalled packages: {len(packages)} total")
            # Show a sample for context
            sample = packages[:20]
            parts.append(f"  Sample: {', '.join(sample)}")

        return "\n".join(parts) if parts else "No system context available"

    def _match_targets(
        self,
        intent: ParsedIntent,
        context: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Match intent targets against actual system resources.

        The LLM should already return matched targets when it has system context.
        This method validates and enhances the matching as needed.
        """
        matched = {}

        if intent.resource_type == "container":
            containers = context.get("container_names", [])
            # Also check containers dict for full info
            all_containers = context.get("containers", {}).get("all", [])
            if all_containers:
                containers = [c.get("name", c.get("id", "")) for c in all_containers]

            matched_containers = []
            for target in intent.targets:
                # Check if target is an exact match (LLM returned actual name)
                if target in containers:
                    matched_containers.append(target)
                else:
                    # Try fuzzy matching (filter term)
                    for container in containers:
                        if target.lower() in container.lower():
                            matched_containers.append(container)
            matched["containers"] = list(set(matched_containers))

        elif intent.resource_type == "service":
            services = context.get("service_names", [])
            # Also get from services list
            if context.get("services"):
                services = [s.get("name", "") for s in context["services"]]

            matched_services = []
            for target in intent.targets:
                # Check exact match first (LLM may return "nginx.service")
                if target in services:
                    matched_services.append(target)
                elif f"{target}.service" in services:
                    matched_services.append(f"{target}.service")
                else:
                    # Fuzzy match
                    for service in services:
                        if target.lower() in service.lower().replace(".service", ""):
                            matched_services.append(service)
            matched["services"] = list(set(matched_services))

        elif intent.resource_type == "package":
            # Packages are typically not pre-enumerated, just pass through targets
            # The LLM should have extracted package names correctly
            matched["packages"] = intent.targets

        return matched

    def _format_matched_resources(self, matched: dict[str, list[str]]) -> str:
        """Format matched resources for LLM."""
        parts = []
        for resource_type, items in matched.items():
            if items:
                parts.append(f"{resource_type.capitalize()}: {', '.join(items)}")
        return "\n".join(parts) if parts else "No specific resources matched"


def create_llm_planner_callback(ollama: OllamaClient | None = None):
    """Create a callback function for TaskPlanner.llm_planner.

    This bridges the LLMPlanner to the existing TaskPlanner interface.
    """
    planner = LLMPlanner(ollama)

    def llm_plan_callback(request: str, context: dict[str, Any]) -> list[dict]:
        """Generate plan steps for a request.

        Returns empty list for queries (no plan needed).
        Returns steps for actions (plan needed).
        """
        # Parse intent
        intent = planner.parse_intent(request, context)

        if intent.confidence < 0.3:
            logger.warning("Low confidence intent parse: %s", intent.explanation)
            return []

        # QUERY actions don't need a plan - let normal agent handle
        if intent.action == "query":
            logger.debug("Query intent detected, no plan needed: %s", intent.explanation)
            return []

        # ACTION intents need a plan
        logger.info("Action intent: %s on %s targets=%s",
                    intent.action, intent.resource_type, intent.targets)

        # Generate plan
        steps = planner.generate_plan(intent, context)

        # Convert to dict format expected by TaskPlanner
        return [
            {
                "id": f"llm_step_{i}",
                "title": step.title,
                "description": step.description,
                "type": "command",
                "action": {
                    "tool": step.tool,
                    "args": step.tool_args,
                },
                "rollback": step.rollback_command,
                "explanation": step.description,
            }
            for i, step in enumerate(steps)
        ]

    return llm_plan_callback

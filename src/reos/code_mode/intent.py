"""Intent Discovery - understanding user intent from multiple sources.

Intent is discovered by synthesizing understanding from:
1. The user's prompt (what they explicitly asked for)
2. The Play context (Act goals, Scene context, historical Beats)
3. The codebase state (existing patterns, architecture, conventions)

This multi-source approach prevents hallucination by grounding intent
in concrete, observable reality.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reos.code_mode.planner import CodeTaskPlan
    from reos.code_mode.project_memory import ProjectMemoryStore
    from reos.code_mode.sandbox import CodeSandbox
    from reos.code_mode.session_logger import SessionLogger
    from reos.code_mode.streaming import ExecutionObserver
    from reos.providers import LLMProvider
    from reos.play_fs import Act

logger = logging.getLogger(__name__)


@dataclass
class PromptIntent:
    """Intent extracted from the user's explicit request."""

    raw_prompt: str
    action_verb: str          # What they want done: "add", "fix", "refactor", etc.
    target: str               # What they want it done to: "function", "test", "module"
    constraints: list[str]    # Any explicit constraints mentioned
    examples: list[str]       # Any examples they provided
    summary: str              # One-sentence summary of the request


@dataclass
class PlayIntent:
    """Intent derived from The Play context."""

    act_goal: str             # The Act's overarching goal
    act_artifact: str         # What artifact this Act produces
    scene_context: str        # Current Scene context if any
    recent_work: list[str]    # Recent Beats/commits showing trajectory
    knowledge_hints: list[str]  # Relevant knowledge from KB


@dataclass
class LayerResponsibility:
    """Describes what a layer/module is responsible for.

    This prevents misplacement of logic by making layer boundaries explicit.
    Extracted from module docstrings and inferred from code patterns.
    """

    file_path: str            # Path to the module
    layer_name: str           # "rpc", "agent", "executor", "storage", etc.
    responsibilities: list[str]  # What this layer DOES
    not_responsible_for: list[str]  # What this layer should NOT do
    source: str               # "docstring", "inferred", "pattern"


@dataclass
class CodebaseIntent:
    """Intent derived from codebase analysis."""

    language: str             # Primary language
    architecture_style: str   # "monolith", "microservices", "layered", etc.
    conventions: list[str]    # Observed conventions (naming, structure)
    related_files: list[str]  # Files likely relevant to this task
    existing_patterns: list[str]  # Patterns to follow
    test_patterns: str        # How tests are structured
    # Layer responsibilities (prevents misplacement)
    layer_responsibilities: list[LayerResponsibility] = field(default_factory=list)


@dataclass
class DiscoveredIntent:
    """Complete intent synthesized from all sources.

    This is the single source of truth for what the system believes
    the user wants. It must be explicit and grounded in evidence.
    """

    # Core understanding
    goal: str                 # Clear statement of what should be accomplished
    why: str                  # Why this matters (from Play context)
    what: str                 # What specifically needs to change
    how_constraints: list[str]  # How it should be done (constraints)

    # Source intents
    prompt_intent: PromptIntent
    play_intent: PlayIntent
    codebase_intent: CodebaseIntent

    # Metadata
    confidence: float         # 0-1 confidence in this understanding
    ambiguities: list[str]    # Things that are unclear
    assumptions: list[str]    # Assumptions being made
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Transparency - what steps were taken during discovery
    discovery_steps: list[str] = field(default_factory=list)  # Log of what ReOS did

    def summary(self) -> str:
        """Generate human-readable summary of discovered intent."""
        lines = [
            "## Discovered Intent",
            "",
            f"**Goal:** {self.goal}",
            f"**Why:** {self.why}",
            f"**What:** {self.what}",
            "",
        ]

        if self.how_constraints:
            lines.append("**Constraints:**")
            for c in self.how_constraints:
                lines.append(f"- {c}")
            lines.append("")

        if self.assumptions:
            lines.append("**Assumptions:**")
            for a in self.assumptions:
                lines.append(f"- {a}")
            lines.append("")

        if self.ambiguities:
            lines.append("**Ambiguities to resolve:**")
            for amb in self.ambiguities:
                lines.append(f"- {amb}")
            lines.append("")

        lines.append(f"**Confidence:** {self.confidence:.0%}")

        return "\n".join(lines)


class IntentDiscoverer:
    """Discovers user intent from multiple sources.

    Uses different analytical perspectives to build a complete picture
    of what the user wants, grounded in observable evidence.

    When a ProjectMemoryStore is provided, recalls project-specific:
    - Decisions ("We use dataclasses, not TypedDict")
    - Patterns ("Tests go in tests/, named test_*.py")
    - Corrections (learned preferences from past sessions)
    """

    def __init__(
        self,
        sandbox: "CodeSandbox",
        llm: "LLMProvider | None" = None,
        project_memory: "ProjectMemoryStore | None" = None,
        observer: "ExecutionObserver | None" = None,
        session_logger: "SessionLogger | None" = None,
    ) -> None:
        self.sandbox = sandbox
        self._llm = llm
        self._project_memory = project_memory
        self._observer = observer
        self._session_logger = session_logger

    def _log(
        self,
        action: str,
        message: str,
        data: dict | None = None,
        level: str = "INFO",
    ) -> None:
        """Log to session logger if available."""
        if self._session_logger is not None:
            if level == "DEBUG":
                self._session_logger.log_debug("intent", action, message, data or {})
            elif level == "WARN":
                self._session_logger.log_warn("intent", action, message, data or {})
            elif level == "ERROR":
                self._session_logger.log_error("intent", action, message, data or {})
            else:
                self._session_logger.log_info("intent", action, message, data or {})

    def _notify(self, message: str) -> None:
        """Notify observer of activity."""
        if self._observer is not None:
            self._observer.on_activity(message, module="IntentDiscoverer")

    def discover(
        self,
        prompt: str,
        act: Act,
        knowledge_context: str = "",
        plan_context: "CodeTaskPlan | None" = None,
    ) -> DiscoveredIntent:
        """Discover intent from all available sources.

        Args:
            prompt: The user's explicit request.
            act: The active Act with context.
            knowledge_context: Optional knowledge base context.
            plan_context: Optional pre-computed plan from CodePlanner.
                         When provided, reuses the plan's file analysis
                         to enhance codebase intent.

        Returns:
            DiscoveredIntent synthesizing all sources.
        """
        # Track what we're doing for transparency
        discovery_steps: list[str] = []

        # Log discovery start
        self._log("discovery_start", "Starting intent discovery", {
            "prompt_preview": prompt[:200],
            "prompt_length": len(prompt),
            "act_title": act.title,
            "has_llm": self._llm is not None,
            "has_project_memory": self._project_memory is not None,
        })

        def log_step(msg: str) -> None:
            """Log a discovery step and notify observer."""
            discovery_steps.append(msg)
            self._notify(msg.split("] ", 1)[-1] if "] " in msg else msg)
            self._log("discovery_step", msg, {}, level="DEBUG")

        # Phase 1: Extract intent from each source
        log_step(f"Analyzing prompt: '{prompt[:50]}...'")
        prompt_intent = self._analyze_prompt(prompt)
        llm_status = "LLM" if self._llm else "heuristic"
        log_step(f"Extracted action='{prompt_intent.action_verb}', target='{prompt_intent.target}' ({llm_status})")

        log_step(f"Reading Act context: '{act.title}'")
        play_intent = self._analyze_play_context(act, knowledge_context)
        log_step(f"Act goal: '{play_intent.act_goal}', artifact: '{play_intent.act_artifact}'")

        log_step("Scanning repository for related files...")
        codebase_intent = self._analyze_codebase(prompt)
        log_step(f"Found {len(codebase_intent.related_files)} related files, language: {codebase_intent.language}")

        # Phase 1.5: Inject plan context if available
        if plan_context is not None:
            log_step(f"Injecting context from {len(plan_context.steps)} plan steps")
            self._inject_plan_context(plan_context, codebase_intent)

        # Phase 1.6: Inject project memory context
        if self._project_memory is not None:
            log_step("Checking project memory for patterns and decisions...")
            self._inject_project_memory(
                prompt, act.repo_path, play_intent, codebase_intent
            )

        # Phase 2: Synthesize into unified intent
        log_step("Synthesizing all sources into unified intent...")
        intent = self._synthesize_intent(
            prompt=prompt,
            prompt_intent=prompt_intent,
            play_intent=play_intent,
            codebase_intent=codebase_intent,
        )

        # Attach discovery steps to the intent
        log_step(f"Goal: '{intent.goal[:60]}...' (confidence: {intent.confidence:.0%})")
        intent.discovery_steps = discovery_steps

        # Log discovery completion
        self._log("discovery_complete", "Intent discovery complete", {
            "goal": intent.goal[:100],
            "confidence": intent.confidence,
            "num_ambiguities": len(intent.ambiguities),
            "num_assumptions": len(intent.assumptions),
            "num_constraints": len(intent.how_constraints),
            "num_related_files": len(codebase_intent.related_files),
            "discovery_steps": len(discovery_steps),
        })

        return intent

    def _inject_plan_context(
        self,
        plan: "CodeTaskPlan",
        codebase_intent: CodebaseIntent,
    ) -> None:
        """Inject pre-computed plan context into codebase intent.

        The CodePlanner already analyzed the repository to create the plan.
        Reuse that analysis rather than rediscovering from scratch.

        Args:
            plan: The pre-computed plan from CodePlanner.
            codebase_intent: The codebase intent to enhance.
        """
        # Add files from plan to related_files
        all_files = set(codebase_intent.related_files)
        all_files.update(plan.context_files)
        all_files.update(plan.files_to_modify)
        all_files.update(plan.files_to_create)
        codebase_intent.related_files = list(all_files)[:15]

        # Extract patterns from plan steps
        step_patterns = []
        for step in plan.steps:
            if step.target_path:
                # Infer patterns from step descriptions
                desc_lower = step.description.lower()
                if "test" in desc_lower:
                    step_patterns.append("Write tests for new functionality")
                if "class" in desc_lower:
                    step_patterns.append("Use class-based structure")
                if "function" in desc_lower or "def " in desc_lower:
                    step_patterns.append("Use function-based structure")

        # Add unique patterns
        existing = set(codebase_intent.existing_patterns)
        for pattern in step_patterns:
            if pattern not in existing:
                codebase_intent.existing_patterns.append(pattern)
                existing.add(pattern)

        logger.info(
            "Injected plan context: %d files, %d patterns from %d steps",
            len(codebase_intent.related_files),
            len(codebase_intent.existing_patterns),
            len(plan.steps),
        )

    def _analyze_prompt(self, prompt: str) -> PromptIntent:
        """Extract intent from the user's explicit prompt."""
        if self._llm is not None:
            return self._analyze_prompt_with_llm(prompt)
        return self._analyze_prompt_heuristic(prompt)

    def _analyze_prompt_heuristic(self, prompt: str) -> PromptIntent:
        """Fallback prompt analysis without LLM."""
        # Simple heuristic extraction
        words = prompt.lower().split()

        # Find action verb
        action_verbs = ["add", "create", "write", "implement", "fix", "debug",
                       "refactor", "update", "modify", "remove", "delete", "test"]
        action_verb = next((w for w in words if w in action_verbs), "implement")

        # Find target
        targets = ["function", "class", "method", "test", "module", "file",
                  "feature", "endpoint", "api", "bug", "error"]
        target = next((w for w in words if w in targets), "code")

        return PromptIntent(
            raw_prompt=prompt,
            action_verb=action_verb,
            target=target,
            constraints=[],
            examples=[],
            summary=prompt[:200],
        )

    def _analyze_prompt_with_llm(self, prompt: str) -> PromptIntent:
        """Extract intent from prompt using LLM."""
        self._notify("Calling LLM to analyze prompt...")
        self._notify(f"  Prompt length: {len(prompt)} chars")

        system = """You analyze user requests to extract structured intent.
Output JSON with these fields:
{
    "action_verb": "the main action (add, fix, create, refactor, etc.)",
    "target": "what the action applies to (function, class, test, etc.)",
    "constraints": ["any explicit constraints or requirements"],
    "examples": ["any examples the user provided"],
    "summary": "one clear sentence summarizing the request"
}"""

        # Log LLM call details
        self._log("llm_call_start", "Starting prompt analysis LLM call", {
            "purpose": "extract_intent",
            "prompt_length": len(prompt),
            "prompt_preview": prompt[:200],
            "system_prompt_length": len(system),
        })

        try:
            self._notify("  Sending to LLM (intent extraction)...")
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=prompt,
                temperature=0.1,
            )
            self._notify(f"  LLM response: {len(response)} chars")

            # Log raw response
            self._log("llm_response", "Received prompt analysis response", {
                "response_length": len(response),
                "response": response,
            })

            data = json.loads(response)
            self._notify(f"  Parsed: action={data.get('action_verb')}, target={data.get('target')}")

            # Log parsed result
            self._log("intent_extracted", "Extracted prompt intent", {
                "action_verb": data.get("action_verb"),
                "target": data.get("target"),
                "constraints": data.get("constraints", []),
                "summary": data.get("summary", "")[:100],
            })

            return PromptIntent(
                raw_prompt=prompt,
                action_verb=data.get("action_verb", "implement"),
                target=data.get("target", "code"),
                constraints=data.get("constraints", []),
                examples=data.get("examples", []),
                summary=data.get("summary", prompt[:200]),
            )
        except Exception as e:
            self._notify(f"LLM prompt analysis failed: {str(e)[:50]}... using heuristics")
            self._log("llm_error", f"Prompt analysis failed: {e}", {
                "error": str(e),
                "fallback": "heuristic",
            }, level="WARN")
            logger.warning("LLM prompt analysis failed: %s", e)
            return self._analyze_prompt_heuristic(prompt)

    def _analyze_play_context(
        self,
        act: Act,
        knowledge_context: str,
    ) -> PlayIntent:
        """Extract intent from The Play context."""
        # Get Act context
        act_goal = act.title
        act_artifact = act.artifact_type or "software"

        # Parse code_config for additional context
        code_config = act.code_config or {}
        language = code_config.get("language", "unknown")

        # Get recent work from git
        recent_work = []
        try:
            commits = self.sandbox.recent_commits(count=5)
            recent_work = [c.message for c in commits]
        except Exception as e:
            logger.debug("Failed to get recent git commits: %s", e)

        # Parse knowledge hints
        knowledge_hints = []
        if knowledge_context:
            # Extract key points from knowledge context
            for line in knowledge_context.split("\n"):
                if line.strip() and len(line) < 200:
                    knowledge_hints.append(line.strip())
            knowledge_hints = knowledge_hints[:5]  # Limit

        return PlayIntent(
            act_goal=act_goal,
            act_artifact=act_artifact,
            scene_context="",  # TODO: Get from active Scene
            recent_work=recent_work,
            knowledge_hints=knowledge_hints,
        )

    def _inject_project_memory(
        self,
        prompt: str,
        repo_path: str,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> None:
        """Inject project memory context into intent.

        Retrieves relevant memories and injects them into:
        - play_intent.knowledge_hints (decisions, learned corrections)
        - codebase_intent.existing_patterns (project patterns)
        - codebase_intent.conventions (inferred from decisions)
        """
        if self._project_memory is None:
            return

        try:
            memory_context = self._project_memory.get_relevant_context(
                repo_path=repo_path,
                prompt=prompt,
                file_paths=codebase_intent.related_files if codebase_intent.related_files else None,
            )

            if memory_context.is_empty():
                return

            # Inject decisions as knowledge hints
            for decision in memory_context.relevant_decisions:
                hint = f"PROJECT DECISION: {decision.decision}"
                if hint not in play_intent.knowledge_hints:
                    play_intent.knowledge_hints.append(hint)

            # Inject patterns into codebase conventions/patterns
            for pattern in memory_context.applicable_patterns:
                if pattern.description not in codebase_intent.existing_patterns:
                    codebase_intent.existing_patterns.append(pattern.description)

            # Inject learned corrections as knowledge hints
            for correction in memory_context.recent_corrections:
                if correction.inferred_rule:
                    hint = f"LEARNED: {correction.inferred_rule}"
                    if hint not in play_intent.knowledge_hints:
                        play_intent.knowledge_hints.append(hint)

            logger.debug(
                "Injected project memory: %d decisions, %d patterns, %d corrections",
                len(memory_context.relevant_decisions),
                len(memory_context.applicable_patterns),
                len(memory_context.recent_corrections),
            )

        except Exception as e:
            logger.warning("Failed to inject project memory: %s", e)

    def _analyze_codebase(self, prompt: str) -> CodebaseIntent:
        """Extract intent from codebase analysis using grep-based search."""
        # Detect language
        self._notify("Detecting project language...")
        language = self._detect_language()
        self._notify(f"  Language: {language}")

        # Detect architecture style
        self._notify("Analyzing architecture style...")
        architecture = self._detect_architecture()
        if architecture:
            self._notify(f"  Architecture: {architecture}")

        # Find related files
        self._notify("Scanning for related files...")
        related = self._find_related_files(prompt)
        if related:
            self._notify(f"  Found {len(related)} related files:")
            for f in related[:5]:  # Show first 5
                self._notify(f"    → {f}")
            if len(related) > 5:
                self._notify(f"    ... and {len(related) - 5} more")
        else:
            self._notify("  No related files found (new project)")

        # Detect conventions
        self._notify("Detecting coding conventions...")
        conventions = self._detect_conventions()
        if conventions:
            self._notify(f"  Conventions: {', '.join(conventions[:3])}")

        # Detect test patterns
        test_patterns = self._detect_test_patterns()
        if test_patterns:
            self._notify(f"  Test patterns: {', '.join(test_patterns[:2])}")

        # Detect layer responsibilities for related files
        layer_responsibilities = self._detect_layer_responsibilities(related)

        return CodebaseIntent(
            language=language,
            architecture_style=architecture,
            conventions=conventions,
            related_files=related,
            existing_patterns=[],
            test_patterns=test_patterns,
            layer_responsibilities=layer_responsibilities,
        )

    def _detect_language(self) -> str:
        """Detect primary language of the codebase."""
        py_files = len(self.sandbox.find_files("**/*.py"))
        ts_files = len(self.sandbox.find_files("**/*.ts"))
        js_files = len(self.sandbox.find_files("**/*.js"))
        rs_files = len(self.sandbox.find_files("**/*.rs"))
        go_files = len(self.sandbox.find_files("**/*.go"))

        counts = {
            "python": py_files,
            "typescript": ts_files,
            "javascript": js_files,
            "rust": rs_files,
            "go": go_files,
        }

        if max(counts.values()) == 0:
            return "unknown"

        return max(counts, key=lambda k: counts[k])

    def _detect_architecture(self) -> str:
        """Detect architecture style from structure."""
        has_src = len(self.sandbox.find_files("src/**/*")) > 0
        has_tests = len(self.sandbox.find_files("tests/**/*")) > 0
        has_services = len(self.sandbox.find_files("**/services/**/*")) > 0
        has_handlers = len(self.sandbox.find_files("**/handlers/**/*")) > 0

        if has_services and has_handlers:
            return "layered"
        if has_src and has_tests:
            return "standard"
        return "flat"

    def _find_related_files(self, prompt: str) -> list[str]:
        """Find files likely relevant to the request using grep-based search."""
        related: list[str] = []

        # Simple grep-based search
        words = prompt.lower().split()
        for word in words:
            if len(word) < 3:  # Skip short words
                continue
            try:
                matches = self.sandbox.grep(
                    pattern=word,
                    glob_pattern="**/*.py",
                    max_results=5,
                )
                for m in matches:
                    if m.path not in related:
                        related.append(m.path)
            except Exception as e:
                logger.debug("Grep search failed for '%s': %s", word, e)

        return related[:10]  # Limit to 10

    def _detect_conventions(self) -> list[str]:
        """Detect coding conventions from the codebase."""
        conventions = []

        # Check for type hints
        try:
            type_hints = self.sandbox.grep(
                pattern=r"def \w+\([^)]*:[^)]+\)",
                glob_pattern="**/*.py",
                max_results=1,
            )
            if type_hints:
                conventions.append("Uses type hints")
        except Exception as e:
            logger.debug("Failed to detect type hints convention: %s", e)

        # Check for docstrings
        try:
            docstrings = self.sandbox.grep(
                pattern=r'""".*"""',
                glob_pattern="**/*.py",
                max_results=1,
            )
            if docstrings:
                conventions.append("Uses docstrings")
        except Exception as e:
            logger.debug("Failed to detect docstring convention: %s", e)

        # Check for dataclasses
        try:
            dataclasses = self.sandbox.grep(
                pattern=r"@dataclass",
                glob_pattern="**/*.py",
                max_results=1,
            )
            if dataclasses:
                conventions.append("Uses dataclasses")
        except Exception as e:
            logger.debug("Failed to detect dataclass convention: %s", e)

        return conventions

    def _detect_test_patterns(self) -> str:
        """Detect how tests are structured."""
        test_files = self.sandbox.find_files("**/test_*.py")
        if test_files:
            return "pytest (test_*.py)"

        spec_files = self.sandbox.find_files("**/*_spec.py")
        if spec_files:
            return "spec (*_spec.py)"

        return "unknown"

    def _detect_layer_responsibilities(
        self,
        related_files: list[str],
    ) -> list[LayerResponsibility]:
        """Detect layer responsibilities for files.

        Extracts responsibilities from:
        1. Module docstrings that declare responsibilities
        2. Inferred patterns from file paths and code structure
        3. Common layer naming conventions

        This helps prevent misplacement of logic by making layer
        boundaries explicit.
        """
        responsibilities: list[LayerResponsibility] = []

        # Layer patterns to look for in file paths
        layer_patterns = {
            "rpc": {
                "patterns": ["rpc", "server", "handler", "endpoint", "api/"],
                "responsibilities": [
                    "Parse and validate incoming requests",
                    "Route requests to appropriate handlers",
                    "Format responses",
                ],
                "not_responsible_for": [
                    "Business logic",
                    "Decision making",
                    "State management",
                    "Domain operations",
                ],
            },
            "agent": {
                "patterns": ["agent", "orchestrat", "coordinator"],
                "responsibilities": [
                    "Orchestrate request handling",
                    "Make routing decisions",
                    "Manage conversation state",
                    "Coordinate between subsystems",
                ],
                "not_responsible_for": [
                    "Low-level execution",
                    "Request parsing",
                    "Response formatting",
                ],
            },
            "executor": {
                "patterns": ["executor", "runner", "worker", "engine"],
                "responsibilities": [
                    "Execute planned operations",
                    "Report execution progress",
                    "Handle execution errors",
                ],
                "not_responsible_for": [
                    "Planning what to execute",
                    "User interaction",
                    "Request routing",
                ],
            },
            "storage": {
                "patterns": ["db", "database", "storage", "repository", "store"],
                "responsibilities": [
                    "Persist and retrieve data",
                    "Manage database connections",
                    "Handle data migrations",
                ],
                "not_responsible_for": [
                    "Business logic",
                    "Request handling",
                    "User interaction",
                ],
            },
            "service": {
                "patterns": ["service", "services/"],
                "responsibilities": [
                    "Implement business logic",
                    "Coordinate domain operations",
                ],
                "not_responsible_for": [
                    "Request parsing",
                    "Response formatting",
                    "Direct user interaction",
                ],
            },
        }

        for file_path in related_files[:10]:  # Limit to avoid too much analysis
            layer_resp = self._analyze_file_layer(file_path, layer_patterns)
            if layer_resp is not None:
                responsibilities.append(layer_resp)

        return responsibilities

    def _analyze_file_layer(
        self,
        file_path: str,
        layer_patterns: dict,
    ) -> LayerResponsibility | None:
        """Analyze a single file for layer responsibility.

        First tries to extract from docstring, then falls back to
        pattern-based inference.
        """
        # Try to read the file's module docstring
        try:
            content = self.sandbox.read_file(file_path, start=1, end=50)
            docstring = self._extract_module_docstring(content)
            if docstring:
                layer_resp = self._parse_docstring_responsibilities(
                    file_path, docstring
                )
                if layer_resp is not None:
                    return layer_resp
        except Exception as e:
            logger.debug("Failed to read file %s for layer analysis: %s", file_path, e)

        # Fall back to pattern-based inference
        file_lower = file_path.lower()
        for layer_name, config in layer_patterns.items():
            for pattern in config["patterns"]:
                if pattern in file_lower:
                    return LayerResponsibility(
                        file_path=file_path,
                        layer_name=layer_name,
                        responsibilities=config["responsibilities"],
                        not_responsible_for=config["not_responsible_for"],
                        source="inferred",
                    )

        return None

    def _extract_module_docstring(self, content: str) -> str | None:
        """Extract module docstring from file content."""
        lines = content.split("\n")
        in_docstring = False
        docstring_lines = []

        for line in lines:
            stripped = line.strip()
            # Skip empty lines and imports at start
            if not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    in_docstring = True
                    # Check for single-line docstring
                    if stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                        return stripped.strip('"""').strip("'''")
                    docstring_lines.append(stripped.lstrip('"""').lstrip("'''"))
                elif stripped.startswith("from ") or stripped.startswith("import "):
                    # Hit imports without docstring
                    return None
                elif stripped and not stripped.startswith("#"):
                    # Non-empty, non-comment line without docstring
                    return None
            else:
                if '"""' in stripped or "'''" in stripped:
                    docstring_lines.append(stripped.rstrip('"""').rstrip("'''"))
                    return "\n".join(docstring_lines)
                docstring_lines.append(stripped)

        return None

    def _parse_docstring_responsibilities(
        self,
        file_path: str,
        docstring: str,
    ) -> LayerResponsibility | None:
        """Parse responsibilities from docstring.

        Looks for explicit declarations like:
        - "This is a..." / "This module..."
        - "Design goals:" sections
        - "This is intentionally NOT..." statements
        """
        responsibilities: list[str] = []
        not_responsible: list[str] = []
        layer_name = "unknown"

        lines = docstring.split("\n")
        for line in lines:
            line_lower = line.lower().strip()

            # Detect layer type
            if "rpc" in line_lower or "json-rpc" in line_lower:
                layer_name = "rpc"
            elif "agent" in line_lower:
                layer_name = "agent"
            elif "executor" in line_lower or "runner" in line_lower:
                layer_name = "executor"
            elif "database" in line_lower or "storage" in line_lower:
                layer_name = "storage"
            elif "service" in line_lower:
                layer_name = "service"

            # Detect responsibilities
            if line_lower.startswith("- ") and ":" not in line_lower:
                responsibilities.append(line.strip("- ").strip())

            # Detect "NOT" statements
            if "not " in line_lower and ("this is" in line_lower or "intentionally" in line_lower):
                not_responsible.append(line.strip())

        if responsibilities or not_responsible or layer_name != "unknown":
            return LayerResponsibility(
                file_path=file_path,
                layer_name=layer_name,
                responsibilities=responsibilities,
                not_responsible_for=not_responsible,
                source="docstring",
            )

        return None

    def _synthesize_intent(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize all intents into unified understanding."""
        if self._llm is not None:
            return self._synthesize_with_llm(
                prompt, prompt_intent, play_intent, codebase_intent
            )
        return self._synthesize_heuristic(
            prompt, prompt_intent, play_intent, codebase_intent
        )

    def _synthesize_heuristic(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize without LLM."""
        goal = prompt_intent.summary
        why = f"Part of {play_intent.act_goal}"
        what = f"{prompt_intent.action_verb} {prompt_intent.target}"

        constraints = list(prompt_intent.constraints)
        if codebase_intent.language != "unknown":
            constraints.append(f"Use {codebase_intent.language}")
        if codebase_intent.conventions:
            constraints.extend(codebase_intent.conventions)

        return DiscoveredIntent(
            goal=goal,
            why=why,
            what=what,
            how_constraints=constraints,
            prompt_intent=prompt_intent,
            play_intent=play_intent,
            codebase_intent=codebase_intent,
            confidence=0.7,
            ambiguities=[],
            assumptions=[],
        )

    def _synthesize_with_llm(
        self,
        prompt: str,
        prompt_intent: PromptIntent,
        play_intent: PlayIntent,
        codebase_intent: CodebaseIntent,
    ) -> DiscoveredIntent:
        """Synthesize using LLM for deeper understanding."""
        self._notify("Calling LLM to synthesize unified intent...")
        self._notify(f"  Sources: prompt + play context + codebase ({len(codebase_intent.related_files)} files)")

        system = """You synthesize user intent from multiple sources into a clear understanding.

Given:
1. The user's prompt and extracted intent
2. The Play context (project goals, recent work)
3. The codebase context (language, architecture, conventions)

Output JSON:
{
    "goal": "Clear, specific statement of what should be accomplished",
    "why": "Why this matters in the context of the project",
    "what": "Specifically what needs to change in the code",
    "how_constraints": ["Constraints on how to implement"],
    "confidence": 0.0-1.0,
    "ambiguities": ["Things that are unclear"],
    "assumptions": ["Assumptions being made"]
}

Be specific. Ground everything in the provided context. Flag ambiguities honestly."""

        # Build layer responsibilities section
        layer_section = ""
        if codebase_intent.layer_responsibilities:
            layer_section = "\n\nLAYER RESPONSIBILITIES (respect these boundaries):"
            for layer in codebase_intent.layer_responsibilities[:5]:
                layer_section += f"\n\n{layer.file_path} ({layer.layer_name} layer):"
                if layer.responsibilities:
                    layer_section += "\n  Does: " + ", ".join(layer.responsibilities[:3])
                if layer.not_responsible_for:
                    layer_section += "\n  Does NOT: " + ", ".join(layer.not_responsible_for[:3])

        context = f"""
USER PROMPT: {prompt}

PROMPT ANALYSIS:
- Action: {prompt_intent.action_verb}
- Target: {prompt_intent.target}
- Summary: {prompt_intent.summary}

PLAY CONTEXT:
- Act Goal: {play_intent.act_goal}
- Artifact: {play_intent.act_artifact}
- Recent Work: {', '.join(play_intent.recent_work[:3])}

CODEBASE CONTEXT:
- Language: {codebase_intent.language}
- Architecture: {codebase_intent.architecture_style}
- Conventions: {', '.join(codebase_intent.conventions)}
- Related Files: {', '.join(codebase_intent.related_files[:5])}
{layer_section}"""

        # Log synthesis LLM call
        self._log("llm_call_start", "Starting intent synthesis LLM call", {
            "purpose": "synthesize_intent",
            "prompt_length": len(prompt),
            "context_length": len(context),
            "related_files": codebase_intent.related_files[:5],
            "act_goal": play_intent.act_goal,
        })

        try:
            self._notify("  Sending to LLM (synthesis)...")
            response = self._llm.chat_json(  # type: ignore
                system=system,
                user=context,
                temperature=0.2,
            )
            self._notify(f"  LLM response: {len(response)} chars")

            # Log raw response
            self._log("llm_response", "Received synthesis response", {
                "response_length": len(response),
                "response": response,
            })

            data = json.loads(response)
            self._notify(f"  Parsed goal: '{data.get('goal', '')[:50]}...'")
            self._notify(f"  Confidence: {data.get('confidence', 0.7):.0%}")
            if data.get("ambiguities"):
                self._notify(f"  Ambiguities: {len(data['ambiguities'])} identified")
            if data.get("assumptions"):
                self._notify(f"  Assumptions: {len(data['assumptions'])} made")

            # Log synthesized intent
            self._log("intent_synthesized", "Synthesized unified intent", {
                "goal": data.get("goal", "")[:100],
                "why": data.get("why", "")[:100],
                "what": data.get("what", "")[:100],
                "confidence": data.get("confidence", 0.7),
                "num_constraints": len(data.get("how_constraints", [])),
                "num_ambiguities": len(data.get("ambiguities", [])),
                "num_assumptions": len(data.get("assumptions", [])),
                "ambiguities": data.get("ambiguities", []),
                "assumptions": data.get("assumptions", []),
            })

            return DiscoveredIntent(
                goal=data.get("goal", prompt_intent.summary),
                why=data.get("why", f"Part of {play_intent.act_goal}"),
                what=data.get("what", f"{prompt_intent.action_verb} {prompt_intent.target}"),
                how_constraints=data.get("how_constraints", []),
                prompt_intent=prompt_intent,
                play_intent=play_intent,
                codebase_intent=codebase_intent,
                confidence=data.get("confidence", 0.7),
                ambiguities=data.get("ambiguities", []),
                assumptions=data.get("assumptions", []),
            )
        except Exception as e:
            self._notify(f"LLM synthesis failed: {str(e)[:50]}... using heuristics")
            self._log("llm_error", f"Synthesis failed: {e}", {
                "error": str(e),
                "fallback": "heuristic",
            }, level="WARN")
            logger.warning("LLM synthesis failed: %s", e)
            return self._synthesize_heuristic(
                prompt, prompt_intent, play_intent, codebase_intent
            )

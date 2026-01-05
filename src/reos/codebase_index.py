"""Codebase Index - Self-awareness for ReOS.

Scans the ReOS source code and creates a structured index so the AI
can answer questions about its own implementation.

Features:
- Python AST parsing for accurate class/function extraction
- TypeScript/Rust regex-based extraction
- Hash-based cache invalidation
- Token budget management (~5,500 tokens)

Usage:
    from reos.codebase_index import get_codebase_context
    context = get_codebase_context()  # Returns formatted markdown
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CACHE_PATH = Path.home() / ".cache" / "reos" / "codebase_index.json"
TOKEN_BUDGET = 5500  # Approximate target tokens for context


@dataclass
class FunctionInfo:
    """Information about a function/method."""

    name: str
    params: str = ""
    docstring: str | None = None
    is_async: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "params": self.params,
            "docstring": self.docstring,
            "is_async": self.is_async,
        }


@dataclass
class ClassInfo:
    """Information about a class/struct."""

    name: str
    docstring: str | None = None
    methods: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "docstring": self.docstring,
            "methods": self.methods,
            "bases": self.bases,
        }


@dataclass
class ModuleSummary:
    """Summary of a source file."""

    path: str
    language: str
    docstring: str | None = None
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "docstring": self.docstring,
            "classes": [c.to_dict() for c in self.classes],
            "functions": [f.to_dict() for f in self.functions],
            "exports": self.exports,
        }


@dataclass
class CodebaseIndex:
    """Complete index of the codebase."""

    version: str
    hash: str
    modules: list[ModuleSummary]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "hash": self.hash,
            "modules": [m.to_dict() for m in self.modules],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodebaseIndex:
        modules = []
        for m in data.get("modules", []):
            classes = [
                ClassInfo(
                    name=c["name"],
                    docstring=c.get("docstring"),
                    methods=c.get("methods", []),
                    bases=c.get("bases", []),
                )
                for c in m.get("classes", [])
            ]
            functions = [
                FunctionInfo(
                    name=f["name"],
                    params=f.get("params", ""),
                    docstring=f.get("docstring"),
                    is_async=f.get("is_async", False),
                )
                for f in m.get("functions", [])
            ]
            modules.append(
                ModuleSummary(
                    path=m["path"],
                    language=m["language"],
                    docstring=m.get("docstring"),
                    classes=classes,
                    functions=functions,
                    exports=m.get("exports", []),
                )
            )
        return cls(
            version=data.get("version", "1.0"),
            hash=data.get("hash", ""),
            modules=modules,
        )

    def to_context_string(self) -> str:
        """Format index as markdown for LLM context injection."""
        lines = [
            "# ReOS Codebase Reference",
            "",
            "This is ReOS - a local-first AI desktop operating system.",
            "Below is a summary of the codebase structure.",
            "",
        ]

        # Group modules by directory
        by_dir: dict[str, list[ModuleSummary]] = {}
        for mod in self.modules:
            dir_name = str(Path(mod.path).parent)
            by_dir.setdefault(dir_name, []).append(mod)

        for dir_path, mods in sorted(by_dir.items()):
            lines.append(f"## {dir_path}/")
            lines.append("")

            for mod in sorted(mods, key=lambda m: m.path):
                name = Path(mod.path).name
                lines.append(f"### {name}")

                if mod.docstring:
                    # Truncate docstring
                    doc = mod.docstring[:150]
                    if len(mod.docstring) > 150:
                        doc += "..."
                    lines.append(f"  {doc}")

                # Show classes
                for cls in mod.classes[:5]:
                    methods_str = ", ".join(cls.methods[:5])
                    if len(cls.methods) > 5:
                        methods_str += ", ..."
                    lines.append(f"  class {cls.name}: {methods_str}")

                # Show top-level functions
                for fn in mod.functions[:5]:
                    async_str = "async " if fn.is_async else ""
                    lines.append(f"  {async_str}def {fn.name}({fn.params})")

                lines.append("")

        return "\n".join(lines)


class CodebaseIndexer:
    """Scans and indexes the ReOS codebase."""

    def __init__(self, project_root: Path | None = None):
        if project_root is None:
            # Find project root (look for pyproject.toml)
            project_root = Path(__file__).parent.parent.parent
        self.root = project_root
        self._index: CodebaseIndex | None = None

    def get_index(self, force_refresh: bool = False) -> CodebaseIndex:
        """Get or build the codebase index.

        Args:
            force_refresh: If True, rebuild even if cache is valid

        Returns:
            CodebaseIndex with module summaries
        """
        current_hash = self._compute_hash()

        # Try cache
        if not force_refresh and CACHE_PATH.exists():
            try:
                cached = json.loads(CACHE_PATH.read_text())
                if cached.get("hash") == current_hash:
                    self._index = CodebaseIndex.from_dict(cached)
                    logger.debug("Loaded codebase index from cache")
                    return self._index
            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("Cache invalid: %s", e)

        # Build fresh
        logger.info("Building codebase index...")
        self._index = self._build_index(current_hash)
        self._save_cache()
        return self._index

    def _compute_hash(self) -> str:
        """Compute hash of all source file modification times."""
        mtimes = []
        for pattern in ["src/**/*.py", "apps/**/*.ts", "apps/**/*.rs"]:
            for path in self.root.glob(pattern):
                if self._should_index(path):
                    mtimes.append(f"{path}:{path.stat().st_mtime}")
        return hashlib.sha256("\n".join(sorted(mtimes)).encode()).hexdigest()[:16]

    def _should_index(self, path: Path) -> bool:
        """Filter out non-essential files."""
        skip_dirs = {
            "node_modules",
            "target",
            "__pycache__",
            ".git",
            "dist",
            "build",
            "gen",
            ".venv",
            "venv",
        }
        skip_files = {"__init__.py"}  # Usually just imports

        # Check directory exclusions
        if any(s in path.parts for s in skip_dirs):
            return False

        # Check file exclusions
        if path.name in skip_files:
            return False

        return True

    def _build_index(self, hash_val: str) -> CodebaseIndex:
        """Build index from source files."""
        modules: list[ModuleSummary] = []

        # Python files
        for path in self.root.glob("src/**/*.py"):
            if self._should_index(path):
                mod = self._parse_python(path)
                if mod and (mod.classes or mod.functions):
                    modules.append(mod)

        # TypeScript files
        for path in self.root.glob("apps/**/*.ts"):
            if self._should_index(path):
                mod = self._parse_typescript(path)
                if mod and (mod.classes or mod.functions or mod.exports):
                    modules.append(mod)

        # Rust files
        for path in self.root.glob("apps/**/src/**/*.rs"):
            if self._should_index(path):
                mod = self._parse_rust(path)
                if mod and (mod.classes or mod.functions):
                    modules.append(mod)

        return CodebaseIndex(
            version="1.0",
            hash=hash_val,
            modules=modules,
        )

    def _parse_python(self, path: Path) -> ModuleSummary | None:
        """Extract Python module structure via AST."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.debug("Failed to parse %s: %s", path, e)
            return None

        docstring = ast.get_docstring(tree)
        classes: list[ClassInfo] = []
        functions: list[FunctionInfo] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                # Get class methods
                methods = [
                    n.name
                    for n in ast.iter_child_nodes(node)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not n.name.startswith("_")
                ]
                # Get base classes
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(base.attr)

                classes.append(
                    ClassInfo(
                        name=node.name,
                        docstring=ast.get_docstring(node),
                        methods=methods[:10],  # Limit methods
                        bases=bases,
                    )
                )

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Top-level functions only (not methods)
                if node.name.startswith("_"):
                    continue

                # Get parameters
                params = []
                for arg in node.args.args[:5]:
                    params.append(arg.arg)
                if len(node.args.args) > 5:
                    params.append("...")
                params_str = ", ".join(params)

                functions.append(
                    FunctionInfo(
                        name=node.name,
                        params=params_str,
                        docstring=ast.get_docstring(node),
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                    )
                )

        return ModuleSummary(
            path=str(path.relative_to(self.root)),
            language="python",
            docstring=docstring,
            classes=classes[:10],  # Limit classes
            functions=functions[:15],  # Limit functions
        )

    def _parse_typescript(self, path: Path) -> ModuleSummary | None:
        """Extract TypeScript structure via regex."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            return None

        # Extract exports
        exports = re.findall(
            r"export\s+(?:function|class|const|interface|type)\s+(\w+)", source
        )

        # Extract functions
        functions: list[FunctionInfo] = []
        for match in re.finditer(
            r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)", source
        ):
            is_async = "async" in match.group(0)
            functions.append(
                FunctionInfo(
                    name=match.group(1),
                    params=match.group(2)[:50],
                    is_async=is_async,
                )
            )

        # Extract classes
        classes: list[ClassInfo] = []
        for match in re.finditer(r"(?:export\s+)?class\s+(\w+)", source):
            classes.append(ClassInfo(name=match.group(1)))

        return ModuleSummary(
            path=str(path.relative_to(self.root)),
            language="typescript",
            docstring=None,
            classes=classes[:5],
            functions=functions[:10],
            exports=exports[:10],
        )

    def _parse_rust(self, path: Path) -> ModuleSummary | None:
        """Extract Rust structure via regex."""
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            return None

        # Module doc
        doc_match = re.search(r"^//!\s*(.+)$", source, re.MULTILINE)
        docstring = doc_match.group(1) if doc_match else None

        # Public functions
        functions: list[FunctionInfo] = []
        for match in re.finditer(
            r"pub\s+(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)", source
        ):
            is_async = "async" in match.group(0)
            functions.append(
                FunctionInfo(
                    name=match.group(1),
                    params=match.group(2)[:50],
                    is_async=is_async,
                )
            )

        # Public structs
        classes: list[ClassInfo] = []
        for match in re.finditer(r"pub\s+struct\s+(\w+)", source):
            classes.append(ClassInfo(name=match.group(1)))

        # Public enums
        for match in re.finditer(r"pub\s+enum\s+(\w+)", source):
            classes.append(ClassInfo(name=match.group(1)))

        return ModuleSummary(
            path=str(path.relative_to(self.root)),
            language="rust",
            docstring=docstring,
            classes=classes[:5],
            functions=functions[:10],
        )

    def _save_cache(self) -> None:
        """Save index to cache file."""
        if self._index is None:
            return

        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(
                json.dumps(self._index.to_dict(), indent=2),
                encoding="utf-8",
            )
            logger.debug("Saved codebase index to cache")
        except Exception as e:
            logger.warning("Failed to save cache: %s", e)


# Singleton indexer
_indexer: CodebaseIndexer | None = None


def get_codebase_context(force_refresh: bool = False) -> str:
    """Get codebase context string for LLM injection.

    Args:
        force_refresh: If True, rebuild the index

    Returns:
        Formatted markdown string describing the codebase
    """
    global _indexer

    if _indexer is None:
        _indexer = CodebaseIndexer()

    index = _indexer.get_index(force_refresh=force_refresh)
    return index.to_context_string()


def get_codebase_index(force_refresh: bool = False) -> CodebaseIndex:
    """Get the raw codebase index.

    Returns:
        CodebaseIndex with full module information
    """
    global _indexer

    if _indexer is None:
        _indexer = CodebaseIndexer()

    return _indexer.get_index(force_refresh=force_refresh)

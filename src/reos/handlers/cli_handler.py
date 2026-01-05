"""CLI Handler - Terminal-specific adapter for ReOS services.

Provides terminal I/O for chat, The Play, knowledge base, context,
and model management - bringing feature parity with the Tauri app.
"""

from __future__ import annotations

import sys
from typing import Any, Callable

from ..db import Database
from ..services.chat_service import ChatService, ChatRequest, ChatResult
from ..services.play_service import PlayService
from ..services.context_service import ContextService
from ..services.knowledge_service import KnowledgeService


class CLIHandler:
    """Terminal-specific handler wrapping shared services.

    Provides CLI commands for all features available in the Tauri app:
    - /play - The Play management
    - /kb - Knowledge base
    - /context - Context usage
    - /compact - Conversation compaction
    - /models - Model management
    - /archives - Archive browsing
    """

    def __init__(self, db: Database):
        self.db = db
        self.chat = ChatService(db)
        self.play = PlayService()
        self.context = ContextService(db)
        self.knowledge = KnowledgeService()

        # Current conversation
        self._conversation_id: str | None = None

    @property
    def conversation_id(self) -> str | None:
        return self._conversation_id

    @conversation_id.setter
    def conversation_id(self, value: str | None) -> None:
        self._conversation_id = value

    # --- Chat ---

    def handle_message(
        self,
        message: str,
        on_approval: Callable[[dict[str, Any]], bool] | None = None,
    ) -> ChatResult:
        """Process a user message.

        Args:
            message: The user's message
            on_approval: Optional callback for approval prompts

        Returns:
            ChatResult with the response
        """
        request = ChatRequest(
            message=message,
            conversation_id=self._conversation_id,
        )

        result = self.chat.respond(request, on_approval_needed=on_approval)

        # Update conversation ID
        if self._conversation_id is None:
            self._conversation_id = result.conversation_id

        return result

    def prompt_approval(self, approval_info: dict[str, Any]) -> bool:
        """Interactive terminal approval prompt.

        Args:
            approval_info: Dict with command, explanation, risk_level

        Returns:
            True if approved, False if rejected
        """
        print("\n--- Approval Required ---")
        print(f"Command: {approval_info.get('command', 'N/A')}")
        if approval_info.get("explanation"):
            print(f"Purpose: {approval_info['explanation']}")
        if approval_info.get("risk_level"):
            print(f"Risk: {approval_info['risk_level']}")
        print("-" * 30)

        while True:
            response = input("Approve? [y/N]: ").strip().lower()
            if response in ("y", "yes"):
                return True
            if response in ("n", "no", ""):
                return False
            print("Please enter 'y' or 'n'")

    # --- Commands ---

    def handle_command(self, command: str, args: list[str]) -> str | None:
        """Handle a CLI command.

        Args:
            command: The command name (without /)
            args: Command arguments

        Returns:
            Output string or None if not a recognized command
        """
        handlers = {
            "play": self._cmd_play,
            "kb": self._cmd_kb,
            "context": self._cmd_context,
            "compact": self._cmd_compact,
            "models": self._cmd_models,
            "archives": self._cmd_archives,
            "clear": self._cmd_clear,
        }

        handler = handlers.get(command.lower())
        if handler:
            return handler(args)
        return None

    # --- /play Command ---

    def _cmd_play(self, args: list[str]) -> str:
        """Handle /play commands.

        Usage:
            /play                  - Show current state
            /play story            - Show your story
            /play acts             - List acts
            /play select <id>      - Select an act
            /play search <query>   - Search The Play
        """
        if not args:
            return self._play_status()

        subcmd = args[0].lower()

        if subcmd == "story":
            story = self.play.read_story()
            return f"--- Your Story ---\n{story}"

        if subcmd == "acts":
            acts, active_id = self.play.list_acts()
            if not acts:
                return "No acts defined. Create one in the Tauri app."

            lines = ["Acts:"]
            for act in acts:
                marker = " *" if act.active else ""
                lines.append(f"  [{act.act_id}] {act.title}{marker}")
            if active_id:
                lines.append(f"\n* = Active act")
            return "\n".join(lines)

        if subcmd == "select" and len(args) > 1:
            act_id = args[1]
            try:
                self.play.set_active_act(act_id)
                return f"Active act set to: {act_id}"
            except ValueError as e:
                return f"Error: {e}"

        if subcmd == "search" and len(args) > 1:
            query = " ".join(args[1:])
            results = self.play.search(query)
            if not results:
                return f"No results for '{query}'"

            lines = [f"Search results for '{query}':"]
            for r in results[:10]:
                lines.append(f"  [{r['type']}] {r.get('title', 'Untitled')}")
                lines.append(f"    {r.get('snippet', '')[:80]}")
            return "\n".join(lines)

        return self._play_help()

    def _play_status(self) -> str:
        """Show current Play status."""
        acts, active_id = self.play.list_acts()

        lines = ["The Play Status:"]
        lines.append(f"  Acts: {len(acts)}")

        if active_id:
            active = next((a for a in acts if a.act_id == active_id), None)
            if active:
                lines.append(f"  Active: {active.title}")
                scenes = self.play.list_scenes(active_id)
                lines.append(f"  Scenes: {len(scenes)}")
        else:
            lines.append("  No active act")

        lines.append("\nCommands: /play story, /play acts, /play select <id>, /play search <query>")
        return "\n".join(lines)

    def _play_help(self) -> str:
        return """Usage: /play [command]

Commands:
  (none)          Show current status
  story           Show your story (me.md)
  acts            List all acts
  select <id>     Set active act
  search <query>  Search The Play content"""

    # --- /kb Command ---

    def _cmd_kb(self, args: list[str]) -> str:
        """Handle /kb (knowledge base) commands.

        Usage:
            /kb                    - Show stats
            /kb list               - List entries
            /kb search <query>     - Search knowledge
            /kb add <content>      - Add entry
        """
        if not args:
            return self._kb_stats()

        subcmd = args[0].lower()

        if subcmd == "list":
            entries = self.knowledge.list_entries(limit=20)
            if not entries:
                return "No learned knowledge yet."

            lines = ["Learned Knowledge:"]
            for e in entries:
                date = e.learned_at[:10] if e.learned_at else ""
                lines.append(f"  [{e.category}] {e.content[:60]}... ({date})")
            return "\n".join(lines)

        if subcmd == "search" and len(args) > 1:
            query = " ".join(args[1:])
            results = self.knowledge.search(query)
            if not results:
                return f"No results for '{query}'"

            lines = [f"Knowledge matching '{query}':"]
            for e in results[:10]:
                lines.append(f"  [{e.category}] {e.content[:70]}...")
            return "\n".join(lines)

        if subcmd == "add" and len(args) > 1:
            content = " ".join(args[1:])
            entry = self.knowledge.add_entry(content)
            if entry:
                return f"Added: [{entry.category}] {entry.content[:50]}..."
            return "Entry not added (may be duplicate)"

        return self._kb_help()

    def _kb_stats(self) -> str:
        """Show knowledge base stats."""
        stats = self.knowledge.get_stats()

        lines = ["Knowledge Base:"]
        lines.append(f"  Total entries: {stats.total_entries}")
        lines.append(f"  Facts: {stats.facts}")
        lines.append(f"  Lessons: {stats.lessons}")
        lines.append(f"  Decisions: {stats.decisions}")
        lines.append(f"  Preferences: {stats.preferences}")
        lines.append(f"  Observations: {stats.observations}")
        lines.append("\nCommands: /kb list, /kb search <query>, /kb add <content>")
        return "\n".join(lines)

    def _kb_help(self) -> str:
        return """Usage: /kb [command]

Commands:
  (none)          Show statistics
  list            List recent entries
  search <query>  Search knowledge
  add <content>   Add new entry (observation)"""

    # --- /context Command ---

    def _cmd_context(self, args: list[str]) -> str:
        """Handle /context commands.

        Usage:
            /context               - Show usage
            /context sources       - Show breakdown
            /context disable <src> - Disable a source
            /context enable <src>  - Enable a source
        """
        if not args:
            return self._context_stats()

        subcmd = args[0].lower()

        if subcmd == "sources":
            stats = self.context.get_stats(
                conversation_id=self._conversation_id,
                include_breakdown=True,
            )
            if not stats.sources:
                return "Source breakdown not available"

            lines = ["Context Sources:"]
            for s in stats.sources:
                status = "ON" if s["enabled"] else "OFF"
                lines.append(f"  {s['display_name']}: {s['tokens']:,} tokens ({s['percent']:.1f}%) [{status}]")
            return "\n".join(lines)

        if subcmd in ("disable", "enable") and len(args) > 1:
            source = args[1]
            enabled = subcmd == "enable"
            try:
                self.context.toggle_source(source, enabled)
                return f"Source '{source}' {'enabled' if enabled else 'disabled'}"
            except Exception as e:
                return f"Error: {e}"

        return self._context_help()

    def _context_stats(self) -> str:
        """Show context usage stats."""
        stats = self.context.get_stats(conversation_id=self._conversation_id)

        # Warning indicator
        warning = ""
        if stats.warning_level == "critical":
            warning = " [CRITICAL]"
        elif stats.warning_level == "warning":
            warning = " [WARNING]"

        lines = ["Context Usage:"]
        lines.append(f"  Used: {stats.estimated_tokens:,} / {stats.context_limit - stats.reserved_tokens:,} tokens{warning}")
        lines.append(f"  Available: {stats.available_tokens:,} tokens")
        lines.append(f"  Usage: {stats.usage_percent:.1f}%")
        lines.append(f"  Messages: {stats.message_count}")
        lines.append("\nCommands: /context sources, /context disable <src>, /context enable <src>")
        return "\n".join(lines)

    def _context_help(self) -> str:
        return """Usage: /context [command]

Commands:
  (none)          Show usage summary
  sources         Show per-source breakdown
  disable <src>   Disable a context source
  enable <src>    Enable a context source

Sources: system_prompt, play_context, learned_kb, system_state"""

    # --- /compact Command ---

    def _cmd_compact(self, args: list[str]) -> str:
        """Handle /compact command.

        Archives current conversation and extracts learned knowledge.
        """
        if not self._conversation_id:
            return "No active conversation to compact"

        # Confirm
        print("This will archive and clear the current conversation.")
        confirm = input("Continue? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            return "Cancelled"

        result = self.context.compact(
            conversation_id=self._conversation_id,
            archive=True,
            extract_knowledge=True,
        )

        if result.success:
            lines = ["Compaction complete:"]
            lines.append(f"  Tokens saved: {result.tokens_saved:,}")
            lines.append(f"  Knowledge entries: {result.learned_entries_added}")
            if result.archive_id:
                lines.append(f"  Archive: {result.archive_id}")
            return "\n".join(lines)
        else:
            return f"Compaction failed: {result.error}"

    # --- /models Command ---

    def _cmd_models(self, args: list[str]) -> str:
        """Handle /models commands.

        Usage:
            /models            - List available models
            /models set <id>   - Set active model
        """
        if not args:
            return self._models_list()

        if args[0].lower() == "set" and len(args) > 1:
            model_id = args[1]
            if self.chat.set_model(model_id):
                return f"Model set to: {model_id}"
            return f"Failed to set model: {model_id}"

        return self._models_help()

    def _models_list(self) -> str:
        """List available models."""
        models = self.chat.list_models()

        if not models:
            return "No models available (is Ollama running?)"

        lines = ["Available Models:"]
        for m in models:
            current = " *" if m.is_current else ""
            caps = []
            if m.capabilities.get("tools"):
                caps.append("tools")
            if m.capabilities.get("thinking"):
                caps.append("thinking")
            if m.capabilities.get("vision"):
                caps.append("vision")
            if m.capabilities.get("code"):
                caps.append("code")
            caps_str = f" [{', '.join(caps)}]" if caps else ""
            lines.append(f"  {m.id}{current}{caps_str}")

        lines.append("\n* = Current model")
        lines.append("Commands: /models set <id>")
        return "\n".join(lines)

    def _models_help(self) -> str:
        return """Usage: /models [command]

Commands:
  (none)       List available models
  set <id>     Set active model"""

    # --- /archives Command ---

    def _cmd_archives(self, args: list[str]) -> str:
        """Handle /archives commands.

        Usage:
            /archives              - List archives
            /archives search <q>   - Search archives
            /archives view <id>    - View archive
        """
        if not args:
            return self._archives_list()

        subcmd = args[0].lower()

        if subcmd == "search" and len(args) > 1:
            query = " ".join(args[1:])
            results = self.context.search_archives(query)
            if not results:
                return f"No archives matching '{query}'"

            lines = [f"Archives matching '{query}':"]
            for a in results[:10]:
                lines.append(f"  [{a['archive_id']}] {a['title']} ({a['message_count']} msgs)")
            return "\n".join(lines)

        if subcmd == "view" and len(args) > 1:
            archive_id = args[1]
            archive = self.context.get_archive(archive_id)
            if not archive:
                return f"Archive not found: {archive_id}"

            lines = [f"Archive: {archive['title']}"]
            lines.append(f"  ID: {archive['archive_id']}")
            lines.append(f"  Created: {archive['created_at']}")
            lines.append(f"  Messages: {archive['message_count']}")
            if archive.get("summary"):
                lines.append(f"  Summary: {archive['summary'][:200]}...")

            lines.append("\nRecent messages:")
            for msg in archive.get("messages", [])[-5:]:
                role = msg.get("role", "?").upper()
                content = msg.get("content", "")[:80]
                lines.append(f"  {role}: {content}...")

            return "\n".join(lines)

        return self._archives_help()

    def _archives_list(self) -> str:
        """List conversation archives."""
        archives = self.context.list_archives()

        if not archives:
            return "No archives yet. Use /compact to archive conversations."

        lines = ["Conversation Archives:"]
        for a in archives[:15]:
            date = a["archived_at"][:10] if a.get("archived_at") else ""
            lines.append(f"  [{a['archive_id']}] {a['title']} ({a['message_count']} msgs, {date})")

        lines.append("\nCommands: /archives search <query>, /archives view <id>")
        return "\n".join(lines)

    def _archives_help(self) -> str:
        return """Usage: /archives [command]

Commands:
  (none)           List recent archives
  search <query>   Search archive content
  view <id>        View archive details"""

    # --- /clear Command ---

    def _cmd_clear(self, args: list[str]) -> str:
        """Handle /clear command."""
        if not self._conversation_id:
            return "No active conversation"

        confirm = input("Clear current conversation? [y/N]: ").strip().lower()
        if confirm not in ("y", "yes"):
            return "Cancelled"

        if self.chat.clear_conversation(self._conversation_id):
            return "Conversation cleared"
        return "Failed to clear conversation"

    # --- Help ---

    def get_commands_help(self) -> str:
        """Get help text for all CLI commands."""
        return """Available Commands:

/play       - Manage The Play (acts, scenes, beats)
/kb         - Knowledge base (learned facts, lessons)
/context    - View/manage context usage
/compact    - Archive and compact conversation
/models     - List and switch AI models
/archives   - Browse conversation archives
/clear      - Clear current conversation
/help       - Show this help

Type /command for detailed help on each command."""

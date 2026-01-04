"""ReOS Shell CLI - Natural language terminal integration.

This module provides a CLI interface for handling natural language prompts
directly from the terminal, enabling shell integration via command_not_found_handle.

Usage:
    python -m reos.shell_cli "what files are in my home directory"
    python -m reos.shell_cli --execute "list all python files"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import NoReturn

from .agent import ChatAgent, ChatResponse
from .db import get_db
from .logging_setup import configure_logging

# File to persist conversation ID between shell invocations
CONVERSATION_FILE = Path.home() / ".reos_conversation"


def get_conversation_id() -> str | None:
    """Get the current conversation ID from file."""
    try:
        if CONVERSATION_FILE.exists():
            content = CONVERSATION_FILE.read_text().strip()
            if content:
                return content
    except Exception:
        pass
    return None


def save_conversation_id(conversation_id: str) -> None:
    """Save conversation ID to file for context continuity."""
    try:
        CONVERSATION_FILE.write_text(conversation_id)
    except Exception:
        pass  # Best effort


def clear_conversation() -> None:
    """Clear the current conversation to start fresh."""
    try:
        if CONVERSATION_FILE.exists():
            CONVERSATION_FILE.unlink()
    except Exception:
        pass


def colorize(text: str, color: str) -> str:
    """Apply ANSI color codes if stdout is a TTY."""
    if not sys.stdout.isatty():
        return text

    colors = {
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "reset": "\033[0m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "white": "\033[97m",
        "bg_dim": "\033[48;5;236m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def print_header() -> None:
    """Print a minimal ReOS header."""
    header = colorize("🐧 ReOS", "cyan") + colorize(" (natural language mode)", "dim")
    print(header, file=sys.stderr)


def print_thinking() -> None:
    """Show thinking indicator."""
    print(colorize("  🤔 Thinking...", "dim"), end="\r", file=sys.stderr)


def clear_thinking() -> None:
    """Clear the thinking indicator."""
    print(" " * 30, end="\r", file=sys.stderr)


def print_processing_summary(response: ChatResponse, *, quiet: bool = False) -> None:
    """Print a summary of what ReOS did during processing.

    This shows tool calls, pending approvals, and other metadata
    in a visually distinct format from the response.
    """
    if quiet:
        return

    has_output = False

    # Show tool calls
    if response.tool_calls:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize("🔧 Actions taken:", "cyan"), file=sys.stderr)

        for tc in response.tool_calls:
            name = tc.get("name", "unknown")
            ok = tc.get("ok", False)

            # Format tool name nicely with category emoji
            display_name = name.replace("linux_", "").replace("reos_", "").replace("_", " ")

            # Pick emoji based on tool category
            if "docker" in name or "container" in name:
                tool_emoji = "🐳"
            elif "service" in name:
                tool_emoji = "🔄"
            elif "package" in name:
                tool_emoji = "📦"
            elif "system_info" in name:
                tool_emoji = "📊"
            elif "run_command" in name:
                tool_emoji = "⚡"
            elif "git" in name:
                tool_emoji = "📂"
            elif "file" in name or "log" in name:
                tool_emoji = "📄"
            elif "network" in name:
                tool_emoji = "🌐"
            elif "process" in name:
                tool_emoji = "⚙️"
            else:
                tool_emoji = "🔹"

            if ok:
                status = colorize("✅", "green")
                # Show brief result preview for some tools
                result = tc.get("result", {})
                preview = ""
                if isinstance(result, dict):
                    if "stdout" in result and result["stdout"]:
                        lines = result["stdout"].strip().split("\n")
                        preview = f" → {len(lines)} lines"
                    elif "hostname" in result:
                        preview = f" → {result.get('hostname', '')}"
                    elif "status" in result:
                        preview = f" → {result.get('status', '')}"
            else:
                status = colorize("❌", "red")
                error = tc.get("error", {})
                preview = f" → {error.get('message', 'failed')}" if error else ""

            print(f"    {status} {tool_emoji} {colorize(display_name, 'cyan')}{colorize(preview, 'dim')}", file=sys.stderr)

        has_output = True

    # Show pending approval
    if response.pending_approval_id:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize("⚠ Pending approval:", "yellow"), file=sys.stderr)
        print(f"    ID: {response.pending_approval_id}", file=sys.stderr)
        print(colorize("    Use 'yes' to approve or 'no' to reject", "dim"), file=sys.stderr)
        has_output = True

    # Show conversation tracking
    if response.conversation_id and not quiet:
        if not has_output:
            print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(colorize(f"📝 Conversation: {response.conversation_id}", "dim"), file=sys.stderr)
        has_output = True

    # Separator before response
    if has_output:
        print(colorize("─" * 50, "dim"), file=sys.stderr)
        print(file=sys.stderr)


def handle_prompt(
    prompt: str,
    *,
    verbose: bool = False,
    conversation_id: str | None = None,
) -> ChatResponse:
    """Process a natural language prompt through ReOS.

    Args:
        prompt: The natural language query from the user.
        verbose: If True, show detailed progress.
        conversation_id: Optional conversation ID to continue.

    Returns:
        ChatResponse with answer and metadata.
    """
    db = get_db()
    agent = ChatAgent(db=db)

    if verbose:
        print_thinking()

    try:
        response = agent.respond(prompt, conversation_id=conversation_id)
    finally:
        if verbose:
            clear_thinking()

    return response


def main() -> NoReturn:
    """Main entry point for shell CLI."""
    configure_logging()

    parser = argparse.ArgumentParser(
        prog="reos-shell",
        description="ReOS natural language terminal integration",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Natural language prompt to process",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress header and progress indicators",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed processing information",
    )
    parser.add_argument(
        "--new", "-n",
        action="store_true",
        help="Start a new conversation (clear previous context)",
    )
    parser.add_argument(
        "--command-not-found",
        action="store_true",
        help="Mode for command_not_found_handle integration (shows prompt confirmation)",
    )

    args = parser.parse_args()

    # Handle --new flag to start fresh conversation
    if args.new:
        clear_conversation()

    # Join prompt words
    prompt = " ".join(args.prompt).strip()

    if not prompt:
        # Read from stdin if no prompt provided
        if not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()

        if not prompt:
            print("Usage: reos-shell 'your natural language prompt'", file=sys.stderr)
            sys.exit(1)

    # In command-not-found mode, confirm before processing
    if args.command_not_found:
        print(colorize("ReOS:", "cyan"), f"'{prompt}' is not a command.", file=sys.stderr)
        print(colorize("      ", "cyan"), "Treat as natural language? [Y/n] ", end="", file=sys.stderr)

        try:
            response = input().strip().lower()
            if response and response not in ("y", "yes"):
                sys.exit(127)  # Standard exit code for command not found
        except (EOFError, KeyboardInterrupt):
            sys.exit(127)

    if not args.quiet:
        print_header()

    try:
        # Get conversation ID for context continuity
        conversation_id = get_conversation_id()

        result = handle_prompt(
            prompt,
            verbose=not args.quiet,
            conversation_id=conversation_id,
        )

        # Save conversation ID for next invocation
        save_conversation_id(result.conversation_id)

        # Show processing summary (tools called, pending approvals, etc.)
        print_processing_summary(result, quiet=args.quiet and not args.verbose)

        # Print the actual response
        if not args.quiet:
            print(colorize("💬 ReOS:", "cyan"), file=sys.stderr)
            print(file=sys.stderr)

        print(result.answer)
        sys.exit(0)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(colorize(f"Error: {e}", "red"), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

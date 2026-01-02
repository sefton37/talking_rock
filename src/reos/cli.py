"""ReOS Command Line Interface.

Provides a modern CLI with subcommands for managing the ReOS attention kernel.

Usage:
    reos status          Show kernel and repo status
    reos kernel          Start the kernel daemon
    reos watch [PATH]    Watch a git repository
    reos review [REF]    Review a commit or range
    reos chat            Start interactive chat
    reos config          Manage configuration
    reos play            Manage Acts/Scenes/Beats
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Optional

try:
    import typer
    from typer import Argument, Option
except ImportError:
    print("Error: typer is required for the CLI. Install with: pip install typer[all]")
    sys.exit(1)

from rich.console import Console
from rich.table import Table

from reos.paths import paths, migrate_legacy_data

# Main app
app = typer.Typer(
    name="reos",
    help="ReOS - Local-first, Git-first attention kernel companion",
    add_completion=True,
    no_args_is_help=True,
)

# Subcommand groups
config_app = typer.Typer(help="Configuration management")
play_app = typer.Typer(help="Manage Acts, Scenes, and Beats")
persona_app = typer.Typer(help="Manage agent personas")

app.add_typer(config_app, name="config")
app.add_typer(play_app, name="play")
app.add_typer(persona_app, name="persona")

console = Console()


def _get_version() -> str:
    """Get package version."""
    try:
        from importlib.metadata import version

        return version("reos")
    except Exception:
        return "0.0.0a0"


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"ReOS version {_get_version()}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        Option("--version", "-V", callback=version_callback, is_eager=True, help="Show version"),
    ] = False,
    verbose: Annotated[
        bool,
        Option("--verbose", "-v", help="Enable verbose output"),
    ] = False,
    json_output: Annotated[
        bool,
        Option("--json", "-j", help="Output in JSON format"),
    ] = False,
) -> None:
    """ReOS - Local-first, Git-first attention kernel companion."""
    # Store flags in context for subcommands
    ctx = typer.Context
    if verbose:
        os.environ["REOS_LOG_LEVEL"] = "DEBUG"


# =============================================================================
# Status Commands
# =============================================================================


@app.command()
def status(
    json_output: Annotated[bool, Option("--json", "-j", help="JSON output")] = False,
) -> None:
    """Show kernel and repository status."""
    from reos.settings import settings
    from reos.ollama import check_ollama

    status_data = {
        "kernel": {
            "data_dir": str(paths.data_home),
            "config_dir": str(paths.config_home),
            "db_exists": paths.db_path.exists(),
        },
        "ollama": {"url": settings.ollama_url, "available": False, "model": None},
        "repo": {"path": str(settings.repo_path) if settings.repo_path else None},
    }

    # Check Ollama
    try:
        ollama_status = check_ollama()
        status_data["ollama"]["available"] = ollama_status.get("available", False)
        status_data["ollama"]["model"] = ollama_status.get("model")
    except Exception:
        pass

    if json_output:
        console.print_json(json.dumps(status_data))
        return

    # Pretty print
    console.print("[bold cyan]ReOS Status[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Data Directory", str(paths.data_home))
    table.add_row("Config Directory", str(paths.config_home))
    table.add_row("Database", "✓ exists" if paths.db_path.exists() else "✗ not found")
    table.add_row(
        "Ollama",
        f"✓ {status_data['ollama']['model']}"
        if status_data["ollama"]["available"]
        else "✗ not available",
    )
    if status_data["repo"]["path"]:
        table.add_row("Repository", status_data["repo"]["path"])

    console.print(table)


# =============================================================================
# Kernel Commands
# =============================================================================


@app.command()
def kernel(
    daemon: Annotated[bool, Option("--daemon", "-d", help="Run as daemon")] = False,
    port: Annotated[int, Option("--port", "-p", help="HTTP port")] = 8010,
    host: Annotated[str, Option("--host", "-H", help="Bind address")] = "127.0.0.1",
) -> None:
    """Start the ReOS kernel."""
    if daemon:
        console.print("[cyan]Starting ReOS kernel as daemon...[/cyan]")
        _daemonize()
    else:
        console.print(f"[cyan]Starting ReOS kernel on {host}:{port}...[/cyan]")

    os.environ["REOS_HOST"] = host
    os.environ["REOS_PORT"] = str(port)

    from reos.app import app as fastapi_app
    import uvicorn

    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


def _daemonize() -> None:
    """Fork into background (Unix only)."""
    if sys.platform == "win32":
        console.print("[red]Daemon mode not supported on Windows[/red]")
        raise typer.Exit(1)

    import os

    # First fork
    if os.fork() > 0:
        raise typer.Exit(0)

    os.setsid()

    # Second fork
    if os.fork() > 0:
        raise typer.Exit(0)

    # Write PID file
    if paths.runtime_dir:
        paths.runtime_dir.mkdir(parents=True, exist_ok=True)
        pid_file = paths.runtime_dir / "reos.pid"
        pid_file.write_text(str(os.getpid()))


@app.command()
def stop() -> None:
    """Stop the running kernel daemon."""
    if not paths.pid_file or not paths.pid_file.exists():
        console.print("[yellow]No running kernel found[/yellow]")
        raise typer.Exit(1)

    import signal

    pid = int(paths.pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        paths.pid_file.unlink()
        console.print("[green]Kernel stopped[/green]")
    except ProcessLookupError:
        paths.pid_file.unlink()
        console.print("[yellow]Kernel was not running (stale PID file removed)[/yellow]")


# =============================================================================
# Watch Commands
# =============================================================================


@app.command()
def watch(
    path: Annotated[
        Optional[Path],
        Argument(help="Repository path to watch"),
    ] = None,
    interval: Annotated[int, Option("--interval", "-i", help="Poll interval in seconds")] = 30,
) -> None:
    """Watch a git repository for changes."""
    repo_path = path or Path.cwd()

    if not (repo_path / ".git").exists():
        console.print(f"[red]Not a git repository: {repo_path}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Watching repository: {repo_path}[/cyan]")
    console.print(f"[dim]Poll interval: {interval}s[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    os.environ["REOS_REPO_PATH"] = str(repo_path)

    from reos.git_poll import run_git_poll_loop

    try:
        run_git_poll_loop(interval_seconds=interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching[/yellow]")


# =============================================================================
# Review Commands
# =============================================================================


@app.command()
def review(
    ref: Annotated[str, Argument(help="Git ref to review (commit, branch, range)")] = "HEAD",
    include_diff: Annotated[bool, Option("--diff", "-d", help="Include full diff")] = False,
    json_output: Annotated[bool, Option("--json", "-j", help="JSON output")] = False,
) -> None:
    """Review a commit or commit range."""
    import subprocess

    # Get commit info
    try:
        result = subprocess.run(
            ["git", "show", "--stat", ref],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to get commit info: {e.stderr}[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Reviewing: {ref}[/cyan]\n")
    console.print(result.stdout)

    # TODO: Call LLM for review
    console.print("\n[dim]LLM review not yet implemented[/dim]")


# =============================================================================
# Chat Commands
# =============================================================================


@app.command()
def chat(
    message: Annotated[
        Optional[str],
        Argument(help="Message to send (interactive if omitted)"),
    ] = None,
) -> None:
    """Start interactive chat or send a single message."""
    from reos.agent import ChatAgent
    from reos.db import get_connection

    agent = ChatAgent(get_connection())

    if message:
        # Single message mode
        response = agent.respond(message)
        console.print(response["answer"])
        return

    # Interactive mode
    console.print("[cyan]ReOS Chat[/cyan] (type 'exit' to quit)\n")

    while True:
        try:
            user_input = console.input("[bold]You:[/bold] ")
            if user_input.lower() in ("exit", "quit", "q"):
                break

            response = agent.respond(user_input)
            console.print(f"\n[bold cyan]ReOS:[/bold cyan] {response['answer']}\n")

        except KeyboardInterrupt:
            break
        except EOFError:
            break

    console.print("\n[dim]Goodbye![/dim]")


# =============================================================================
# Config Commands
# =============================================================================


@config_app.command("show")
def config_show(
    json_output: Annotated[bool, Option("--json", "-j", help="JSON output")] = False,
) -> None:
    """Show current configuration."""
    from reos.settings import settings

    config_data = {
        "log_level": settings.log_level,
        "host": settings.host,
        "port": settings.port,
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
        "repo_path": str(settings.repo_path) if settings.repo_path else None,
        "llm_context_tokens": settings.llm_context_tokens,
        "auto_review_commits": settings.auto_review_commits,
    }

    if json_output:
        console.print_json(json.dumps(config_data))
        return

    table = Table(title="ReOS Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    for key, value in config_data.items():
        table.add_row(key, str(value) if value is not None else "[dim]not set[/dim]")

    console.print(table)


@config_app.command("path")
def config_path() -> None:
    """Show configuration file path."""
    console.print(str(paths.config_file))


@config_app.command("edit")
def config_edit() -> None:
    """Open configuration file in editor."""
    import subprocess

    editor = os.environ.get("EDITOR", "vi")

    # Ensure config dir exists
    paths.config_home.mkdir(parents=True, exist_ok=True)

    # Create default config if not exists
    if not paths.config_file.exists():
        paths.config_file.write_text(_default_config())
        console.print(f"[dim]Created default config at {paths.config_file}[/dim]")

    subprocess.run([editor, str(paths.config_file)])


@config_app.command("migrate")
def config_migrate() -> None:
    """Migrate data from legacy .reos-data directory."""
    if migrate_legacy_data():
        console.print("[green]Migration complete![/green]")
        console.print(f"Data migrated to: {paths.data_home}")
    else:
        console.print("[yellow]No legacy data found to migrate[/yellow]")


def _default_config() -> str:
    """Generate default configuration file content."""
    return """\
# ReOS Configuration
# https://github.com/your-org/reos

[general]
# Log level: DEBUG, INFO, WARNING, ERROR
log_level = "INFO"

[kernel]
# Kernel bind address
host = "127.0.0.1"
port = 8010

[ollama]
# Local Ollama endpoint
url = "http://127.0.0.1:11434"
# Model to use (leave empty for auto-detect)
# model = "llama3.2"

[review]
# Automatic commit review
auto_review = false
include_diff = false
cooldown_seconds = 5

[context]
# LLM context window settings
max_tokens = 8192
trigger_ratio = 0.8
cooldown_minutes = 15
"""


# =============================================================================
# Play Commands
# =============================================================================


@play_app.command("list")
def play_list(
    act_id: Annotated[Optional[str], Option("--act", "-a", help="Filter by act")] = None,
    json_output: Annotated[bool, Option("--json", "-j", help="JSON output")] = False,
) -> None:
    """List acts, scenes, or beats."""
    from reos.play_fs import PlayFS

    play = PlayFS(paths.play_dir)

    if act_id:
        scenes = play.list_scenes(act_id)
        if json_output:
            console.print_json(json.dumps(scenes))
        else:
            for scene in scenes:
                console.print(f"  {scene['id']}: {scene['title']}")
    else:
        acts = play.list_acts()
        if json_output:
            console.print_json(json.dumps(acts))
        else:
            for act in acts:
                active = "→ " if act.get("active") else "  "
                console.print(f"{active}{act['id']}: {act['title']}")


@play_app.command("create")
def play_create(
    title: Annotated[str, Argument(help="Title for the new act")],
    notes: Annotated[str, Option("--notes", "-n", help="Optional notes")] = "",
) -> None:
    """Create a new act."""
    from reos.play_fs import PlayFS

    play = PlayFS(paths.play_dir)
    act_id = play.create_act(title=title, notes=notes)
    console.print(f"[green]Created act: {act_id}[/green]")


# =============================================================================
# Persona Commands
# =============================================================================


@persona_app.command("list")
def persona_list(
    json_output: Annotated[bool, Option("--json", "-j", help="JSON output")] = False,
) -> None:
    """List available personas."""
    from reos.db import get_connection

    conn = get_connection()
    cursor = conn.execute("SELECT id, name, is_active FROM agent_personas ORDER BY name")
    personas = [{"id": row[0], "name": row[1], "active": bool(row[2])} for row in cursor.fetchall()]

    if json_output:
        console.print_json(json.dumps(personas))
        return

    for p in personas:
        active = "→ " if p["active"] else "  "
        console.print(f"{active}{p['name']} ({p['id']})")


@persona_app.command("activate")
def persona_activate(
    persona_id: Annotated[str, Argument(help="Persona ID to activate")],
) -> None:
    """Set the active persona."""
    from reos.db import get_connection

    conn = get_connection()
    conn.execute("UPDATE agent_personas SET is_active = 0")
    conn.execute("UPDATE agent_personas SET is_active = 1 WHERE id = ?", (persona_id,))
    conn.commit()
    console.print(f"[green]Activated persona: {persona_id}[/green]")


# =============================================================================
# Completions
# =============================================================================


@app.command(hidden=True)
def completions(
    shell: Annotated[str, Argument(help="Shell type: bash, zsh, fish")],
) -> None:
    """Generate shell completions."""
    import subprocess

    # Typer's built-in completion generation
    result = subprocess.run(
        [sys.executable, "-m", "typer", "reos.cli", "run", "--install-completion", shell],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        console.print(f"[green]Installed {shell} completions[/green]")
    else:
        # Fallback: print completion script
        console.print(f"[yellow]Run: eval \"$(reos --install-completion {shell})\"[/yellow]")


# =============================================================================
# Entry Point
# =============================================================================


def main_cli() -> None:
    """Main entry point for the CLI."""
    # Ensure XDG directories exist
    paths.ensure_dirs()

    # Check for legacy data migration
    from reos.paths import get_legacy_data_dir

    if get_legacy_data_dir() and not paths.db_path.exists():
        console.print(
            "[yellow]Legacy .reos-data directory found. "
            "Run 'reos config migrate' to migrate.[/yellow]"
        )

    app()


if __name__ == "__main__":
    main_cli()

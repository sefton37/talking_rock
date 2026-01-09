"""ReOS Shell Propose - Propose commands, never execute.

This module implements the "Foreign until confirmed" principle:
- Takes natural language input
- Proposes a shell command
- Prints command and explanation to stdout
- NEVER EXECUTES ANYTHING

The shell script handles confirmation and native execution.

Output format:
  Line 1: The proposed command
  Line 2+: Explanation (optional)

Usage:
  python -m reos.shell_propose "install gimp"
  # Output:
  # sudo apt install gimp
  # Installs GIMP image editor using apt package manager
"""

from __future__ import annotations

import re
import sys
from typing import NoReturn

from .db import get_db
from .providers import get_provider


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 1: Output Sanitization (assume garbage in)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_command(raw_response: str) -> tuple[str | None, str]:
    """
    LLMs will do all of these despite instructions:
    - Wrap in ```bash ... ```
    - Wrap in single backticks
    - Add explanations before/after
    - Return "bash" or "shell" as literals
    - Answer the question instead of commanding
    - Prefix with "Command:" or "Run:"
    - Add "LINE 1:" prefix

    Returns:
        Tuple of (command or None, explanation)
    """
    text = raw_response.strip()
    explanation = ""

    # Strip markdown code blocks (``` or ```bash or ```shell)
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```bash) and find closing ```
        code_lines = []
        after_lines = []
        in_code = True
        for line in lines[1:]:
            if line.strip() == "```":
                in_code = False
                continue
            if in_code:
                code_lines.append(line)
            else:
                after_lines.append(line)
        text = "\n".join(code_lines).strip()
        # Anything after the code block might be explanation
        if after_lines:
            explanation = " ".join(l.strip() for l in after_lines if l.strip())

    # Strip single backticks wrapping the entire response
    if text.startswith("`") and text.endswith("`") and text.count("`") == 2:
        text = text[1:-1].strip()

    # Handle multiple lines - first line is command, rest is explanation
    if "\n" in text:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            first_line = lines[0]
            # Strip backticks from first line
            first_line = first_line.strip("`").strip()
            if looks_like_command(first_line):
                text = first_line
                if len(lines) > 1:
                    explanation = " ".join(lines[1:])

    # Strip common prefixes
    for prefix in ["Command:", "Run:", "Execute:", "$ ", "> ", "Output:",
                   "LINE 1:", "Line 1:", "line 1:", "bash ", "shell "]:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].strip()

    # Strip any remaining backticks
    text = text.strip("`").strip()

    # Clean explanation prefixes
    for prefix in ["Explanation:", "LINE 2:", "Line 2:", "This command"]:
        if explanation.lower().startswith(prefix.lower()):
            explanation = explanation[len(prefix):].strip()

    # Reject meta-responses that aren't actual commands
    if text.lower() in ["bash", "shell", "linux", "terminal", "", "none"]:
        return None, "Could not interpret as a command"

    # Validate it's actually a plausible command
    if not looks_like_command(text):
        return None, "Response doesn't look like a shell command"

    return text, explanation


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 2: Command Validation (verify before proposing)
# ═══════════════════════════════════════════════════════════════════════════════

def looks_like_command(text: str) -> bool:
    """
    A command should:
    - Start with a word that could be a binary/builtin
    - Not be a complete English sentence
    - Not be a question
    - Not contain only articles/pronouns/prepositions
    """
    if not text or len(text) > 500:  # Commands don't need to be essays
        return False

    # Questions aren't commands
    if text.rstrip().endswith("?"):
        return False

    words = text.split()
    if not words:
        return False

    first_word = words[0].lower()

    # Common sentence starters that aren't commands
    sentence_starters = {
        "the", "a", "an", "this", "that", "i", "you",
        "it", "there", "here", "what", "who", "when",
        "where", "why", "how", "is", "are", "was", "were",
        "will", "would", "could", "should", "can", "may",
        "to", "for", "of", "in", "on", "at", "by", "with"
    }

    if first_word in sentence_starters:
        return False

    # If it has too many words and reads like prose, reject
    if len(words) > 15:
        # Allow if it has shell operators (pipes, redirects, etc.)
        if not any(c in text for c in ['|', '>', '<', '&&', '||', ';', '$', '/']):
            return False

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 3: Safety Validation (reject dangerous commands)
# ═══════════════════════════════════════════════════════════════════════════════

def is_safe_command(command: str) -> tuple[bool, str]:
    """
    Check if command matches known dangerous patterns.

    Returns:
        Tuple of (is_safe, reason if unsafe)
    """
    dangerous_patterns = [
        (r"rm\s+-rf\s+/\s*$", "Cannot remove root filesystem"),
        (r"rm\s+-rf\s+/\*", "Cannot remove root filesystem"),
        (r"rm\s+-rf\s+~", "Cannot remove home directory"),
        (r"dd\s+if=.*of=/dev/sd", "Cannot write directly to disk"),
        (r"dd\s+if=/dev/zero", "Cannot wipe disk with zeros"),
        (r"dd\s+if=/dev/random", "Cannot overwrite with random data"),
        (r"dd\s+if=/dev/urandom", "Cannot overwrite with random data"),
        (r"mkfs\s+/dev/sd", "Cannot format disk"),
        (r"mkfs\.\w+\s+/dev/sd", "Cannot format disk"),
        (r":\(\)\s*\{.*\}", "Fork bombs are not allowed"),
        (r">\s*/dev/sd", "Cannot write directly to disk"),
        (r"chmod\s+-R\s+777\s+/", "Cannot make all files world-writable"),
    ]

    for pattern, reason in dangerous_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, reason

    return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# Layer 4: Main Proposal Logic (with retry)
# ═══════════════════════════════════════════════════════════════════════════════

# Standard prompt with examples
STANDARD_PROMPT = """You are a Linux command translator. Convert natural language requests into shell commands.

OUTPUT FORMAT (exactly two lines, no exceptions):
LINE 1: The exact shell command to run (no backticks, no markdown, no code blocks)
LINE 2: Brief explanation (one sentence)

CRITICAL RULES:
- Output EXACTLY two lines, nothing more, nothing less
- Line 1 must be a complete, runnable shell command
- No markdown formatting whatsoever (no ```, no `, no *)
- Use sudo when the operation requires root privileges
- For package installation: sudo apt install <package>
- For package removal: sudo apt remove <package>

EXAMPLES:

Request: "install gimp"
sudo apt install gimp
Installs the GIMP image editor

Request: "remove firefox"
sudo apt remove firefox
Removes the Firefox browser

Request: "list files"
ls -la
Lists all files including hidden ones

Request: "show running processes"
ps aux
Shows all running processes

Request: "start nginx"
sudo systemctl start nginx
Starts the nginx service

Request: "show disk usage"
df -h
Shows disk space usage

Request: "who am I"
whoami
Shows current username"""

# Constrained prompt for retry
CONSTRAINED_PROMPT = """Output ONLY a shell command. No explanation. No markdown. No backticks.
One line only. If you cannot help, output exactly: NONE

Task: {intent}"""


def propose_command(natural_language: str) -> tuple[str, str]:
    """Propose a shell command for natural language input.

    Args:
        natural_language: The user's natural language request

    Returns:
        Tuple of (command, explanation)
        - command: The shell command to run (empty string if failed)
        - explanation: Brief explanation of what it does

    Kernel: "Verify it's a command, or retry. Never propose garbage."
    NEVER EXECUTES ANYTHING.
    """
    db = get_db()
    llm = get_provider(db)

    # First attempt: standard prompt
    try:
        response = llm.chat_text(
            system=STANDARD_PROMPT,
            user=f"Request: {natural_language}",
            temperature=0.3,
        )

        command, explanation = extract_command(response)

        if command:
            # Safety check
            is_safe, reason = is_safe_command(command)
            if not is_safe:
                return "", f"Safety: {reason}"
            return command, explanation

    except Exception as e:
        pass  # Fall through to retry

    # Second attempt: constrained prompt
    try:
        response = llm.chat_text(
            system="You are a shell command generator. Output only commands.",
            user=CONSTRAINED_PROMPT.format(intent=natural_language),
            temperature=0.1,  # Even lower temperature for more deterministic output
        )

        # For constrained prompt, just take the first line
        text = response.strip().split("\n")[0].strip()
        text = text.strip("`").strip()

        # Check for explicit failure
        if text.upper() == "NONE":
            return "", "Could not determine a command for that request"

        # Validate
        if looks_like_command(text):
            is_safe, reason = is_safe_command(text)
            if not is_safe:
                return "", f"Safety: {reason}"
            return text, ""

    except Exception as e:
        return "", f"Error: {e}"

    return "", "Could not interpret as a command"


def main() -> NoReturn:
    """Main entry point for shell propose CLI."""
    if len(sys.argv) < 2:
        print("Usage: python -m reos.shell_propose 'natural language request'", file=sys.stderr)
        sys.exit(1)

    # Join all arguments as the natural language input
    natural_language = ' '.join(sys.argv[1:])

    command, explanation = propose_command(natural_language)

    if not command:
        # If we got an error, print it and exit with error code
        if explanation:
            print(explanation, file=sys.stderr)
        sys.exit(1)

    # Output format: command on line 1, explanation on line 2+
    print(command)
    if explanation:
        print(explanation)

    sys.exit(0)


if __name__ == "__main__":
    main()

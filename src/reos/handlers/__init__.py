"""Handlers Package - Interface adapters for CLI and RPC.

Handlers adapt the shared services to specific I/O formats:
    - cli_handler: Terminal I/O, streaming, interactive prompts
    - rpc_handler: JSON-RPC serialization for Tauri

Architecture:
    services/       <- Business logic (shared)
    handlers/       <- This package: I/O adapters

Usage:
    # CLI
    from reos.handlers import CLIHandler
    handler = CLIHandler(db)
    await handler.chat("hello")

    # RPC
    from reos.handlers import RPCHandler
    handler = RPCHandler(db)
    result = handler.chat_respond({"text": "hello"})
"""

from .cli_handler import CLIHandler

__all__ = [
    "CLIHandler",
]

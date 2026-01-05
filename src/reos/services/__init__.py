"""Services Layer - Unified business logic for CLI and RPC interfaces.

This module provides shared services that ensure feature parity between
the CLI (shell_cli.py) and Tauri RPC (ui_rpc_server.py) interfaces.

Architecture:
    services/           <- This package: shared business logic
        chat_service    <- Chat, streaming, model management
        play_service    <- The Play file management
        context_service <- Context management, compaction
        knowledge_service <- Knowledge base, archives

    handlers/           <- Interface adapters (created separately)
        cli_handler     <- CLI-specific I/O
        rpc_handler     <- RPC-specific serialization

Design Principles:
    - Services are stateless (accept db/dependencies via constructor)
    - All business logic lives here, not in handlers
    - Handlers only translate between service interface and I/O format
    - New features are added to services, automatically available to both interfaces
"""

from .chat_service import ChatService
from .play_service import PlayService
from .context_service import ContextService
from .knowledge_service import KnowledgeService

__all__ = [
    "ChatService",
    "PlayService",
    "ContextService",
    "KnowledgeService",
]

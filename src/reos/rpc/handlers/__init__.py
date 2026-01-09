"""RPC handlers organized by domain.

Each handler module uses the @register decorator to register handlers:

    from reos.rpc.router import register

    @register("domain/method")
    def handle_method(*, param1: str, param2: int) -> dict[str, Any]:
        ...

    @register("domain/method_with_db", needs_db=True)
    def handle_method_with_db(db: Database, *, param: str) -> dict[str, Any]:
        ...

Handler modules are imported in router.register_handlers() to populate the registry.
"""

from __future__ import annotations

# Import all handler modules to register them
from reos.rpc.handlers import approvals  # noqa: F401
from reos.rpc.handlers import auth  # noqa: F401
from reos.rpc.handlers import conversations  # noqa: F401
from reos.rpc.handlers import ollama  # noqa: F401
from reos.rpc.handlers import play  # noqa: F401
from reos.rpc.handlers import providers  # noqa: F401
from reos.rpc.handlers import system  # noqa: F401
from reos.rpc.handlers import tools  # noqa: F401

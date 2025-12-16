from __future__ import annotations

import uvicorn

from .settings import settings


def main() -> None:
    uvicorn.run(
        "reos.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()

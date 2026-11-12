"""Healthcheck do Compose: cada servico toca um arquivo enquanto o laco principal vive."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Final

from eyewatcher.settings import Settings

HEARTBEAT: Final[Path] = Path("/tmp/eyewatcher-heartbeat")
MAX_AGE_S: Final[float] = 30.0


def configure_logging(cfg: Settings) -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    # O httpx registra cada requisicao; a API consulta o Ollama o tempo todo.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def heartbeat_loop() -> None:
    while True:
        HEARTBEAT.touch()
        await asyncio.sleep(5)


def main() -> int:
    try:
        return 0 if time.time() - HEARTBEAT.stat().st_mtime < MAX_AGE_S else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Ponto de entrada do container da API."""

from __future__ import annotations

import uvicorn

from eyewatcher.api.app import create_app
from eyewatcher.healthcheck import configure_logging
from eyewatcher.settings import get_settings


def main() -> None:
    cfg = get_settings()
    configure_logging(cfg)
    uvicorn.run(create_app(), host="0.0.0.0", port=8000, log_level="warning")


if __name__ == "__main__":
    main()

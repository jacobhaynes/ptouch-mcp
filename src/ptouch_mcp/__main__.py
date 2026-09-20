"""Entry point: `python -m ptouch_mcp` or the `ptouch-mcp` script."""

from __future__ import annotations

import logging
import os

import uvicorn

from .config import Config


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PTOUCH_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    cfg = Config.from_env()
    uvicorn.run("ptouch_mcp.service:app", host=cfg.listen_host, port=cfg.port, log_config=None)


if __name__ == "__main__":
    main()

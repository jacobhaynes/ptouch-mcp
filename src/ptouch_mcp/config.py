"""Runtime configuration, all of it from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _num(name: str, default: float, cast=float):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    backend: str = "hardware"
    transport: str = "usb"
    model: str = "PT-P710BT"
    host: str = ""
    network_port: int = 9100
    tape_mm: float = 24
    margin_mm: float = 3.0
    font: str = ""
    dry_run_dir: str = "/tmp/ptouch-mcp"
    max_copies: int = 20
    max_text: int = 200
    listen_host: str = "0.0.0.0"
    port: int = 8080

    @classmethod
    def from_env(cls) -> "Config":
        backend = os.environ.get("PTOUCH_BACKEND", cls.backend).strip().lower()
        if backend not in {"hardware", "dry"}:
            raise ValueError(f'PTOUCH_BACKEND must be "hardware" or "dry", got {backend!r}')
        transport = os.environ.get("PTOUCH_TRANSPORT", cls.transport).strip().lower()
        if transport not in {"usb", "network"}:
            raise ValueError(f'PTOUCH_TRANSPORT must be "usb" or "network", got {transport!r}')
        return cls(
            backend=backend,
            transport=transport,
            model=os.environ.get("PTOUCH_MODEL", cls.model),
            host=os.environ.get("PTOUCH_HOST_ADDR", cls.host),
            network_port=_num("PTOUCH_NETWORK_PORT", cls.network_port, int),
            tape_mm=_num("PTOUCH_TAPE_MM", cls.tape_mm),
            margin_mm=_num("PTOUCH_MARGIN_MM", cls.margin_mm),
            font=os.environ.get("PTOUCH_FONT", cls.font),
            dry_run_dir=os.environ.get("PTOUCH_DRY_RUN_DIR", cls.dry_run_dir),
            max_copies=_num("PTOUCH_MAX_COPIES", cls.max_copies, int),
            max_text=_num("PTOUCH_MAX_TEXT", cls.max_text, int),
            listen_host=os.environ.get("PTOUCH_LISTEN_HOST", cls.listen_host),
            port=_num("PTOUCH_PORT", cls.port, int),
        )

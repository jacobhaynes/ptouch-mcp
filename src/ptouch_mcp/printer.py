"""Getting a built label onto tape.

Three backends: USB, network (port 9100), and a dry run that writes PNGs and
prints nothing. They share one small interface so the service does not care which
is in use.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from ptouch import (
    ConnectionNetwork,
    ConnectionUSB,
    LabelPrinter,
    PrinterConnectionError,
    PrinterNotFoundError,
    PrinterPermissionError,
    PrinterTimeoutError,
    PrinterWriteError,
)

from .config import Config
from .labels import BuiltLabel, build, resolve_model, supported_tape_mm

log = logging.getLogger(__name__)

# Everything the library can raise that means "the print did not happen".
PTOUCH_ERRORS = (
    PrinterConnectionError,
    PrinterNotFoundError,
    PrinterPermissionError,
    PrinterTimeoutError,
    PrinterWriteError,
)


class PrinterError(RuntimeError):
    """The print could not be carried out. The message is safe to show a user."""


@dataclass
class Status:
    connected: bool
    model: str
    transport: str
    tape_mm: float
    supported_tape_mm: list[float] = field(default_factory=list)
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "model": self.model,
            "transport": self.transport,
            "tape_mm": self.tape_mm,
            "supported_tape_mm": self.supported_tape_mm,
            "detail": self.detail,
        }


@dataclass
class PrintResult:
    copies: int
    tape_mm: float
    width_px: int
    size_mm: tuple[float, float]
    files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = {
            "copies": self.copies,
            "tape_mm": self.tape_mm,
            "width_px": self.width_px,
            "size_mm": [round(self.size_mm[0], 1), round(self.size_mm[1], 1)],
        }
        if self.files:
            out["files"] = self.files
        return out


class Backend:
    """Common behaviour: build the label, then hand it to the transport."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.model = resolve_model(cfg.model)
        self.transport = "none"

    @property
    def supported_tape_mm(self) -> list[float]:
        return supported_tape_mm(self.model)

    def build(self, text: str, tape_mm: float | None, align: str = "center") -> BuiltLabel:
        return build(
            text,
            tape_mm if tape_mm is not None else self.cfg.tape_mm,
            self.model,
            align=align,
            font=self.cfg.font or None,
        )

    def status(self) -> Status:  # pragma: no cover - overridden
        raise NotImplementedError

    def emit(self, built: BuiltLabel, copies: int, another) -> list[str]:  # pragma: no cover
        """Send `copies` of `built`. `another()` builds a further identical label."""
        raise NotImplementedError

    def print(self, text: str, copies: int, tape_mm: float | None, align: str) -> PrintResult:
        built = self.build(text, tape_mm, align)
        files = self.emit(built, copies, lambda: self.build(text, tape_mm, align))
        log.info(
            "printed %d copy/copies of %r on %smm tape via %s",
            copies, text, built.tape_mm, self.transport,
        )
        return PrintResult(
            copies=copies,
            tape_mm=built.tape_mm,
            width_px=built.label.image.width,
            size_mm=built.size_mm,
            files=files,
        )


class DryBackend(Backend):
    """Writes what would have been printed. Touches no hardware."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self.transport = "dry"
        self.out_dir = Path(cfg.dry_run_dir)

    def status(self) -> Status:
        return Status(
            connected=True,
            model=self.cfg.model,
            transport="dry",
            tape_mm=self.cfg.tape_mm,
            supported_tape_mm=self.supported_tape_mm,
            detail=f"dry run; nothing is printed. PNGs are written to {self.out_dir}",
        )

    def emit(self, built: BuiltLabel, copies: int, another) -> list[str]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        png = built.png()
        files = []
        for n in range(1, copies + 1):
            path = self.out_dir / f"label-{stamp}-{n:02d}.png"
            path.write_bytes(png)
            files.append(str(path))
        return files


class HardwareBackend(Backend):
    """Prints for real, over USB or over the network."""

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)
        self.transport = cfg.transport

    def _connect(self) -> tuple[LabelPrinter, object]:
        if self.cfg.transport == "network":
            if not self.cfg.host:
                raise PrinterError("PTOUCH_HOST_ADDR must be set when PTOUCH_TRANSPORT=network")
            conn = ConnectionNetwork(self.cfg.host, port=self.cfg.network_port)
        else:
            conn = ConnectionUSB()
        printer = self.model(conn)
        try:
            conn.connect(printer)
        except PrinterPermissionError as exc:
            raise PrinterError(
                f"{exc} On Linux, run the container with /dev/bus/usb mounted. "
                "On macOS the kernel claims printer-class devices and libusb cannot "
                "take them -- use PTOUCH_BACKEND=dry there."
            ) from exc
        except PTOUCH_ERRORS as exc:
            raise PrinterError(str(exc)) from exc
        return printer, conn

    def status(self) -> Status:
        try:
            printer, conn = self._connect()
        except PrinterError as exc:
            return Status(
                connected=False,
                model=self.cfg.model,
                transport=self.transport,
                tape_mm=self.cfg.tape_mm,
                supported_tape_mm=self.supported_tape_mm,
                detail=str(exc),
            )
        try:
            return Status(
                connected=True,
                model=self.cfg.model,
                transport=self.transport,
                tape_mm=self.cfg.tape_mm,
                supported_tape_mm=self.supported_tape_mm,
                detail="printer reachable",
            )
        finally:
            conn.close()

    def emit(self, built: BuiltLabel, copies: int, another) -> list[str]:
        printer, conn = self._connect()
        try:
            if copies == 1:
                printer.print(built.label, margin_mm=self.cfg.margin_mm)
            else:
                # A fresh label object per copy -- print_multi prepares each one.
                # half_cut is passed as the printer's own capability: the PT-P710BT
                # ignores the half-cut command, so it needs full cuts to separate
                # the labels at all.
                labels = [built.label] + [another().label for _ in range(copies - 1)]
                printer.print_multi(
                    labels, margin_mm=self.cfg.margin_mm, half_cut=self.model.SUPPORTS_HALF_CUT
                )
        except PTOUCH_ERRORS as exc:
            raise PrinterError(f"printing failed: {exc}") from exc
        finally:
            conn.close()
        return []


def make_backend(cfg: Config) -> Backend:
    return DryBackend(cfg) if cfg.backend == "dry" else HardwareBackend(cfg)

"""Turning text into a label sized for a particular printer and tape.

The `ptouch` library owns the hard parts -- per-printer pin configurations, the
raster format, the cut commands. This module is the thin layer above it: pick a
font, pick a tape, hand back something printable (and previewable).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from ptouch import (
    PTE550W,
    PTP750W,
    PTP900,
    PTP900W,
    PTP910BT,
    PTP950NW,
    LabelPrinter,
    PTP710BT,
    Tape3_5mm,
    Tape6mm,
    Tape9mm,
    Tape12mm,
    Tape18mm,
    Tape24mm,
    Tape36mm,
    TextLabel,
)

MODELS: dict[str, type[LabelPrinter]] = {
    "PT-P710BT": PTP710BT,
    "PT-E550W": PTE550W,
    "PT-P750W": PTP750W,
    "PT-P900": PTP900,
    "PT-P900W": PTP900W,
    "PT-P910BT": PTP910BT,
    "PT-P950NW": PTP950NW,
}

# Tape width in mm -> the library's tape class. Which of these a given printer
# actually accepts comes from its own PIN_CONFIGS, not from this table.
TAPES = {
    3.5: Tape3_5mm,
    6: Tape6mm,
    9: Tape9mm,
    12: Tape12mm,
    18: Tape18mm,
    24: Tape24mm,
    36: Tape36mm,
}

# First one present wins. DejaVu ships in the container; the rest let this run on a
# developer's machine.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]

ALIGN = {
    "left": TextLabel.Align.LEFT | TextLabel.Align.VCENTER,
    "center": TextLabel.Align.HCENTER | TextLabel.Align.VCENTER,
    "right": TextLabel.Align.RIGHT | TextLabel.Align.VCENTER,
}


class LabelError(ValueError):
    """The label could not be built. The message is safe to show a user."""


@dataclass
class BuiltLabel:
    label: TextLabel
    tape_mm: float
    print_pins: int
    dpi: int

    @property
    def size_mm(self) -> tuple[float, float]:
        img = self.label.image
        per_px = 25.4 / self.dpi
        return (img.width * per_px, img.height * per_px)

    def png(self) -> bytes:
        buf = io.BytesIO()
        self.label.image.save(buf, format="PNG")
        return buf.getvalue()


def find_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    raise LabelError(
        "no usable font found. Install fonts-dejavu-core, or set PTOUCH_FONT to a "
        ".ttf path."
    )


def resolve_model(name: str) -> type[LabelPrinter]:
    try:
        return MODELS[name.upper()]
    except KeyError:
        raise LabelError(
            f"unknown printer model {name!r}; known models: {', '.join(sorted(MODELS))}"
        ) from None


def supported_tape_mm(model: type[LabelPrinter]) -> list[float]:
    """Tape widths this printer has a pin configuration for, narrowest first."""
    by_class = {cls: mm for mm, cls in TAPES.items()}
    return sorted(by_class[cls] for cls in model.PIN_CONFIGS if cls in by_class)


def build(
    text: str,
    tape_mm: float,
    model: type[LabelPrinter],
    align: str = "center",
    font: str | None = None,
) -> BuiltLabel:
    """Render `text` for `tape_mm` tape on `model`.

    Height comes from the printer's own pin configuration for that tape -- the
    printable dot count, which is narrower than the tape itself because the edge
    pins are unused.
    """
    if not text.strip():
        raise LabelError("label text is empty")
    if align not in ALIGN:
        raise LabelError(f"align must be one of {', '.join(ALIGN)}")

    tape_cls = TAPES.get(tape_mm)
    if tape_cls is None:
        raise LabelError(f"unknown tape width {tape_mm}mm; known: {sorted(TAPES)}")

    config = model.PIN_CONFIGS.get(tape_cls)
    if config is None:
        supported = ", ".join(f"{mm}mm" for mm in supported_tape_mm(model))
        raise LabelError(
            f"{model.__name__} does not support {tape_mm}mm tape. Supported: {supported}"
        )

    label = TextLabel(text, tape_cls, font=font or find_font(), align=ALIGN[align])
    dpi = model.RESOLUTION_DPI
    label.prepare(config.print_pins, dpi)
    return BuiltLabel(label=label, tape_mm=tape_mm, print_pins=config.print_pins, dpi=dpi)

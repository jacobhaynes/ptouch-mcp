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

# First one present wins.
#
# Regular weights, not bold: P-touch's own default face is Helsinki Regular, and
# bold reads heavy on narrow tape.
#
# Helsinki itself is Brother's font, shipped with P-touch Editor. It is not
# redistributed here -- this only looks for a copy you already have installed, and
# falls back to a free Helvetica-metric clone (Nimbus Sans) otherwise.
BROTHER_FONT_DIR = (
    "/Applications/Brother P-touch Editor.app/Contents/Frameworks"
    "/BRLBXWrapperMac.framework/Versions/A/Resources/fonts.bundle"
)

FONT_CANDIDATES = [
    f"{BROTHER_FONT_DIR}/BRHELRS0.TTF",                        # Helsinki Regular
    "/usr/share/fonts/truetype/urw-base35/NimbusSans-Regular.t1",
    "/usr/share/fonts/truetype/urw-base35/NimbusSans-Regular.otf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

# Convenience names for PTOUCH_FONT, so a compose file can say "helsinki-narrow"
# rather than carry an absolute path.
FONT_ALIASES = {
    "helsinki": f"{BROTHER_FONT_DIR}/BRHELRS0.TTF",
    "helsinki-bold": f"{BROTHER_FONT_DIR}/BRHELBS0.TTF",
    "helsinki-narrow": f"{BROTHER_FONT_DIR}/BRHENRS0.TTF",
    "brussels": f"{BROTHER_FONT_DIR}/BRBRURS0.TTF",
}

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
    tape_cls: type
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


def resolve_font(spec: str | None) -> str:
    """Turn PTOUCH_FONT into a usable path: an alias, a path, or the best default."""
    if spec:
        path = FONT_ALIASES.get(spec.strip().lower(), spec)
        if not Path(path).is_file():
            known = ", ".join(sorted(FONT_ALIASES))
            raise LabelError(f"font {spec!r} not found (looked at {path}). Aliases: {known}")
        return path
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    raise LabelError(
        "no usable font found. Install fonts-urw-base35, or set PTOUCH_FONT to a "
        "font file."
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

    label = TextLabel(text, tape_cls, font=resolve_font(font), align=ALIGN[align])
    dpi = model.RESOLUTION_DPI
    label.prepare(config.print_pins, dpi)
    return BuiltLabel(
        label=label,
        tape_mm=tape_mm,
        tape_cls=tape_cls,
        print_pins=config.print_pins,
        dpi=dpi,
    )

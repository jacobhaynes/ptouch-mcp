"""Turning text into a label sized for a particular printer and tape.

The `ptouch` library owns the hard parts -- per-printer pin configurations, the
raster format, the cut commands. This module is the thin layer above it: pick a
font, pick a tape, hand back something printable (and previewable).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
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
    Label,
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

ALIGNMENTS = ("left", "center", "right")

# Blank columns at each end of the label, on top of the tape margin the printer
# feeds. Keeps text off the cut edge.
LEAD_IN_PX = 12

# Largest type, as a fraction of the printable height. Matches what the library's
# own auto-sizing uses, and leaves a little air top and bottom.
MAX_FILL = 0.80

# Rows of white kept at the top and bottom of the printable area, so ink never
# runs right to the edge (which multi-line labels otherwise do).
EDGE_GUARD_PX = 2


class LabelError(ValueError):
    """The label could not be built. The message is safe to show a user."""


# The printer's own conversion: anything at least half covered becomes a dot.
_THRESHOLD = [0] * 128 + [255] * 128


def to_bitmap(image: Image.Image) -> Image.Image:
    """Exactly what the printer will put on the tape."""
    return image.convert("L").point(_THRESHOLD, mode="1")


@dataclass
class BuiltLabel:
    label: Label
    tape_mm: float
    tape_cls: type
    print_pins: int
    dpi: int
    image: Image.Image
    x_scale: int = 1

    @property
    def size_mm(self) -> tuple[float, float]:
        # Across the tape the resolution is fixed by the print head; along it a
        # high-resolution feed fits x_scale times as many dots into the same mm.
        return (
            self.image.width * 25.4 / (self.dpi * self.x_scale),
            self.image.height * 25.4 / self.dpi,
        )

    def png(self) -> bytes:
        """Preview as the printer will render it, thresholded rather than greyscale.

        A smooth antialiased preview would flatter the result: none of that grey
        reaches the tape.
        """
        buf = io.BytesIO()
        to_bitmap(self.image).save(buf, format="PNG")
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


def render_text(
    lines: list[str],
    height_px: int,
    font_path: str,
    align: str = "center",
    pad_px: int = LEAD_IN_PX,
    x_scale: int = 1,
) -> Image.Image:
    """Lay out `lines` in an image exactly `height_px` tall.

    Vertical placement centres the *body* of the text -- cap top of the first line
    down to the baseline of the last -- rather than the ink bounding box. Those are
    not the same thing: a descender drags the ink box down, which pushes the visible
    letters up by half the tail. On 12mm tape the `y` in "To Dry Cleaner" shifts the
    whole word 0.56mm high, which is plainly visible on a 10mm-tall label, while
    all-caps text looks fine. Centring on the baseline makes every label sit the
    same way regardless of which glyphs happen to be in it.

    Rendered greyscale, not 1-bit. The printer is black-and-white and the library
    hard-thresholds at 50% coverage, but drawing straight into mode "1" uses
    FreeType's monochrome rasteriser, whose glyphs are visibly chunkier than an
    antialiased render thresholded at the same level.

    `x_scale` > 1 renders at that multiple along the tape, for printers that can
    feed at a higher resolution than their print head is wide. Type is drawn at
    `x_scale` times the size and then squeezed back vertically, so the glyphs keep
    their proportions but gain horizontal detail -- which is where the staircase on
    curves and diagonals lives.
    """
    if x_scale > 1:
        tall = render_text(lines, height_px * x_scale, font_path, align, pad_px * x_scale)
        return tall.resize((tall.width, height_px), Image.LANCZOS)

    probe = ImageDraw.Draw(Image.new("1", (1, 1)))

    def layout(size: int):
        font = ImageFont.truetype(font_path, size)
        ascent, _ = font.getmetrics()
        advance = sum(font.getmetrics())            # natural line height
        boxes = [font.getbbox(ln) for ln in lines]
        width = max(b[2] - b[0] for b in boxes)
        cap_top = boxes[0][1]                       # ink top of the first line
        baseline_last = (len(lines) - 1) * advance + ascent
        ink_top = cap_top
        ink_bottom = max(b[3] + i * advance for i, b in enumerate(boxes))
        return font, ascent, advance, boxes, width, ink_top, ink_bottom, baseline_last

    # Largest size whose ink still fits the printable height, edge guard included.
    usable = height_px - 2 * EDGE_GUARD_PX
    lo, hi, best = 6, max(8, int(height_px * MAX_FILL)), 6
    while lo <= hi:
        mid = (lo + hi) // 2
        *_, ink_top, ink_bottom, _ = layout(mid)
        if ink_bottom - ink_top <= usable:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1

    font, ascent, advance, boxes, width, cap_top, ink_bottom, baseline_last = layout(best)

    img = Image.new("L", (width + 2 * pad_px, height_px), 255)   # 255 = white
    draw = ImageDraw.Draw(img)

    # Put the midpoint of (cap top .. last baseline) on the centre line.
    origin_y = round(height_px / 2 - (cap_top + baseline_last) / 2)
    # ...but never let a descender or an ascender fall off the tape.
    origin_y = min(origin_y, height_px - EDGE_GUARD_PX - 1 - ink_bottom)
    origin_y = max(origin_y, EDGE_GUARD_PX - cap_top)

    for i, (line, box) in enumerate(zip(lines, boxes)):
        line_w = box[2] - box[0]
        if align == "left":
            x = pad_px
        elif align == "right":
            x = img.width - pad_px - line_w
        else:
            x = (img.width - line_w) // 2
        draw.text((x - box[0], origin_y + i * advance), line, font=font, fill=0)

    return img


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
    x_scale: int = 1,
) -> BuiltLabel:
    """Render `text` for `tape_mm` tape on `model`.

    Height comes from the printer's own pin configuration for that tape -- the
    printable dot count, which is narrower than the tape itself because the edge
    pins are unused.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise LabelError("label text is empty")
    if align not in ALIGNMENTS:
        raise LabelError(f"align must be one of {', '.join(ALIGNMENTS)}")

    tape_cls = TAPES.get(tape_mm)
    if tape_cls is None:
        raise LabelError(f"unknown tape width {tape_mm}mm; known: {sorted(TAPES)}")

    config = model.PIN_CONFIGS.get(tape_cls)
    if config is None:
        supported = ", ".join(f"{mm}mm" for mm in supported_tape_mm(model))
        raise LabelError(
            f"{model.__name__} does not support {tape_mm}mm tape. Supported: {supported}"
        )

    dpi = model.RESOLUTION_DPI
    image = render_text(
        lines,
        config.print_pins,
        resolve_font(font),
        align=align,
        pad_px=LEAD_IN_PX,
        x_scale=x_scale,
    )
    label = Label(image, tape_cls)
    return BuiltLabel(
        label=label,
        image=image,
        tape_mm=tape_mm,
        tape_cls=tape_cls,
        print_pins=config.print_pins,
        dpi=dpi,
        x_scale=x_scale,
    )

import pytest

from ptouch_mcp.labels import LabelError, build, resolve_model, supported_tape_mm

P710 = resolve_model("PT-P710BT")


def test_supported_tapes_match_the_printers_pin_configs():
    assert supported_tape_mm(P710) == [3.5, 6, 9, 12, 18, 24]


@pytest.mark.parametrize(
    "tape_mm,pins", [(3.5, 24), (6, 32), (9, 50), (12, 70), (18, 112), (24, 128)]
)
def test_label_height_is_the_printable_pin_count(tape_mm, pins):
    """Not the tape width in dots -- the edge pins do not print."""
    built = build("Test", tape_mm, P710)
    assert built.print_pins == pins
    assert built.label.image.height == pins


def test_longer_text_is_wider():
    assert build("ABCDEFGHIJ", 24, P710).label.image.width > build("AB", 24, P710).label.image.width


def test_multiline_stays_within_the_tape():
    assert build("one\ntwo\nthree", 24, P710).label.image.height == 128


def test_rejects_tape_the_printer_cannot_take():
    with pytest.raises(LabelError, match="does not support 36mm"):
        build("x", 36, P710)


def test_rejects_unknown_tape_width():
    with pytest.raises(LabelError, match="unknown tape width"):
        build("x", 15, P710)


def test_rejects_empty_text():
    with pytest.raises(LabelError, match="empty"):
        build("   ", 24, P710)


def test_rejects_unknown_model():
    with pytest.raises(LabelError, match="unknown printer model"):
        resolve_model("PT-NOPE")


def test_rejects_bad_alignment():
    with pytest.raises(LabelError, match="align must be one of"):
        build("x", 24, P710, align="diagonal")


def test_size_mm_matches_180dpi():
    built = build("x", 24, P710)
    assert built.dpi == 180
    assert built.size_mm[1] == pytest.approx(128 * 25.4 / 180, abs=0.01)


def test_png_round_trips():
    assert build("Garage", 24, P710).png()[:8] == b"\x89PNG\r\n\x1a\n"


def test_ink_is_actually_drawn():
    darkest, _ = build("III", 24, P710).label.image.convert("L").getextrema()
    assert darkest == 0

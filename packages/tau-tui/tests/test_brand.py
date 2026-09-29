"""The rasterised mark, the header glyph and the glyph vocabulary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from helpers import make_app
from rich.cells import cell_len
from tau_tui.brand import BREATHE, COMET, TauGlyph, mark_preview, mark_text, rasterise
from tau_tui.theme import GLYPHS_ASCII, GLYPHS_UNICODE, PALETTE, Glyphs

FIXTURES = Path(__file__).parent / "fixtures"
SHA256_24 = "2b79dedaa9a4d36412e73f5155486eaf357a038a52127ac35a37501928df3952"


def test_mark_previews_match_the_pinned_fixtures() -> None:
    for cols in (24, 16):
        expected = (FIXTURES / f"mark_{cols}.txt").read_text(encoding="utf-8").splitlines()
        assert mark_preview(cols) == expected


def test_rasterise_24_is_pinned_with_colours() -> None:
    digest = hashlib.sha256(json.dumps(rasterise(24)).encode()).hexdigest()
    assert digest == SHA256_24


def test_every_cell_is_one_wide_and_within_the_palette() -> None:
    channels = [
        (min(int(c[i : i + 2], 16) for c in PALETTE), max(int(c[i : i + 2], 16) for c in PALETTE))
        for i in (1, 3, 5)
    ]
    for cols in (24, 16):
        cells = rasterise(cols)
        assert len(cells) == cols // 2 and all(len(line) == cols for line in cells)
        for line in cells:
            for char, fg, bg in line:
                assert cell_len(char) == 1
                for colour in (fg, bg):
                    if colour is None:
                        continue
                    for (low, high), i in zip(channels, (1, 3, 5), strict=True):
                        assert low <= int(colour[i : i + 2], 16) <= high


def test_rasterise_is_pure() -> None:
    assert rasterise(16) == rasterise(16)
    assert mark_text(24).plain.splitlines() == [
        "".join(char for char, _, _ in line) for line in rasterise(24)
    ]


def test_glyphs_are_one_cell_and_have_ascii_counterparts() -> None:
    for name, glyph in GLYPHS_UNICODE.as_dict().items():
        assert cell_len(glyph) == 1, name
        assert len(getattr(GLYPHS_ASCII, name)) == 1
        assert getattr(GLYPHS_ASCII, name).isascii()
    assert Glyphs.unicode() == GLYPHS_UNICODE


def test_breathe_and_comet_frames() -> None:
    assert len(BREATHE) == 10 and len(COMET) == 8
    assert BREATHE[0].upper() == "#FF7A3D" and BREATHE[-1].upper() == "#FF7A3D"
    assert all(frame.startswith("#") for frame in BREATHE + COMET)


async def test_glyph_without_motion_creates_no_timer(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)):
        glyph = app.query_one("#glyph", TauGlyph)
        assert glyph.timers == (None, None)
        assert glyph.state == "welcome"


async def test_glyph_with_motion_creates_two_paused_timers(tmp_path: Path) -> None:
    app = make_app(tmp_path, [], motion=True)
    async with app.run_test(size=(80, 24)) as pilot:
        glyph = app.query_one("#glyph", TauGlyph)
        if app.animation_level != "full":
            assert glyph.timers == (None, None)
            return
        breathe, comet = glyph.timers
        assert breathe is not None and comet is not None
        assert breathe._active.is_set() and not comet._active.is_set()  # welcome: breathing
        glyph.state = "busy"
        await pilot.pause()
        assert not breathe._active.is_set() and comet._active.is_set()
        glyph.state = "idle"
        await pilot.pause()
        assert not breathe._active.is_set() and not comet._active.is_set()


def test_ascii_mark_uses_the_three_ascii_blocks(monkeypatch) -> None:
    monkeypatch.setenv("TAU_TUI_ASCII", "1")
    text = mark_text(24)
    assert set(text.plain) <= {" ", "^", "_", "#", "\n"}
    expected = [
        line.replace("█", "#").replace("▀", "^").replace("▄", "_") for line in mark_preview(24)
    ]
    assert text.plain.splitlines() == expected
    styles = {str(span.style).upper() for span in text.spans}
    assert styles == {"#FF7A3D"}  # Ember only, no backgrounds
    monkeypatch.delenv("TAU_TUI_ASCII")
    text = mark_text(24)  # back to the half blocks with a background for the bottom pixel
    assert set(text.plain) <= {" ", "▀", "▄", "\n"}
    assert any(span.style.bgcolor is not None for span in text.spans)

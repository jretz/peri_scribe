"""Row shading leaves terminal content without row styling intact."""

import pytest
import rich.segment
import textual.color

import peri_scribe.monitor.striping
import peri_scribe.monitor.theme


def test_alternating_rows_apply_preserves_unstyled_segments() -> None:
    segments = [rich.segment.Segment("Plain terminal text")]
    shaded = peri_scribe.monitor.striping.AlternatingRows().apply(
        segments,
        textual.color.Color.parse("#282726"),
    )
    assert shaded == segments


@pytest.mark.parametrize(
    "background",
    ["#1c1b1a", "#282726", "#eeeeee", "#ffffff", "#000000", "#ff0000", "#00ff00"],
)
@pytest.mark.parametrize(
    "tint",
    [
        peri_scribe.monitor.theme.YELLOW,
        peri_scribe.monitor.theme.RED,
        peri_scribe.monitor.theme.GREEN,
    ],
)
def test_tint_background_preserves_brightness_and_stays_in_gamut(
    background: str,
    tint: str,
) -> None:
    original = textual.color.Color.parse(background)
    tinted = peri_scribe.monitor.striping.tint_background(
        original,
        textual.color.Color.parse(tint),
    )
    assert tinted.brightness == pytest.approx(original.brightness, abs=0.5 / 255)
    assert tinted == tinted.clamped


def test_tint_background_preserves_a_matching_color_and_alpha() -> None:
    original = textual.color.Color(40, 39, 38, a=0.5)
    assert peri_scribe.monitor.striping.tint_background(original, original) == original

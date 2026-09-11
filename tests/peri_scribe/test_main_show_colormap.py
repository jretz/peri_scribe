"""Show-colormap command tests for peri_scribe.main."""

from __future__ import annotations

import typing

import peri_scribe.kml.colormap
import peri_scribe.main


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def recording_renderer(
    calls: list[tuple[int, int]],
    strip: str,
) -> typing.Callable[..., str]:
    """Return a colormap renderer that records each call's trim window.

    Args:
        calls: The list the renderer appends each (trim_start, trim_end) to.
        strip: The text the renderer returns.

    Returns:
        The stand-in renderer.
    """

    def render(*, trim_start: int, trim_end: int) -> str:
        calls.append((trim_start, trim_end))
        return strip

    return render


def test_show_turbo_colormap_prints_the_strip(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        recording_renderer(calls, strip),
    )
    result = runner.invoke(peri_scribe.main.cli, ["show-colormap"])
    assert result.exit_code == 0
    assert calls == [
        (
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_START,
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_END,
        ),
    ]
    assert result.output == f"{strip}\n"


def test_show_turbo_colormap_passes_trim_options(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        recording_renderer(calls, strip),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["show-colormap", "--trim-start", "16", "--trim-end", "8"],
    )
    assert result.exit_code == 0
    assert calls == [(16, 8)]

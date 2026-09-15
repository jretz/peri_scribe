"""Show-colormap command tests for peri_scribe.main."""

from __future__ import annotations

import typing

import peri_scribe.kml.colormap
import peri_scribe.main
import tests.peri_scribe.main_show_colormap_helpers


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_show_turbo_colormap_prints_the_strip(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        tests.peri_scribe.main_show_colormap_helpers.recording_renderer(calls, strip),
    )
    result = runner.invoke(peri_scribe.main.cli, ["show-colormap"])
    assert result.exit_code == 0
    assert calls == [
        (
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_START,
            peri_scribe.kml.colormap.TURBO_TRIM_FROM_END,
        ),
    ]
    assert result.stdout == f"{strip}\n"
    assert result.stderr == ""


def test_show_turbo_colormap_passes_trim_options(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    strip = "fake-strip"

    monkeypatch.setattr(
        peri_scribe.kml.colormap,
        "turbo_colormap_ansi",
        tests.peri_scribe.main_show_colormap_helpers.recording_renderer(calls, strip),
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["show-colormap", "--trim-start", "16", "--trim-end", "8"],
    )
    assert result.exit_code == 0
    assert calls == [(16, 8)]

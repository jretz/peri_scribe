"""Show-turbo-colormap command tests for peri_scribe.main."""

from __future__ import annotations

import base64
import pathlib
import typing

import peri_scribe.kml.colormap
import peri_scribe.main


if typing.TYPE_CHECKING:
    import click.testing
    import pytest


def test_show_turbo_colormap_prints_inline_image(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    png = b"fake-png-bytes"

    def render(*, trim_start: int, trim_end: int) -> bytes:
        calls.append((trim_start, trim_end))
        return png

    monkeypatch.setattr(peri_scribe.kml.colormap, "turbo_colormap_png", render)
    result = runner.invoke(peri_scribe.main.cli, ["show-turbo-colormap"])
    assert result.exit_code == 0
    assert calls == [(0, 0)]
    encoded = base64.b64encode(png).decode("ascii")
    assert result.output == f"\x1b]1337;File=inline=1;width=100%:{encoded}\a\n"


def test_show_turbo_colormap_passes_trim_options(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
) -> None:
    calls: list[tuple[int, int]] = []
    png = b"fake-png-bytes"

    def render(*, trim_start: int, trim_end: int) -> bytes:
        calls.append((trim_start, trim_end))
        return png

    monkeypatch.setattr(peri_scribe.kml.colormap, "turbo_colormap_png", render)
    result = runner.invoke(
        peri_scribe.main.cli,
        ["show-turbo-colormap", "--trim-start", "16", "--trim-end", "8"],
    )
    assert result.exit_code == 0
    assert calls == [(16, 8)]


def test_show_turbo_colormap_writes_png_file(
    monkeypatch: pytest.MonkeyPatch,
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    calls: list[tuple[int, int]] = []
    png = b"fake-png-bytes"

    def render(*, trim_start: int, trim_end: int) -> bytes:
        calls.append((trim_start, trim_end))
        return png

    monkeypatch.setattr(peri_scribe.kml.colormap, "turbo_colormap_png", render)
    output_path = tmp_path / "nested" / "colormap.png"
    result = runner.invoke(
        peri_scribe.main.cli,
        ["show-turbo-colormap", "--output", str(output_path)],
    )
    assert result.exit_code == 0
    assert calls == [(0, 0)]
    assert "\x1b]1337" not in result.output
    assert output_path.read_bytes() == png

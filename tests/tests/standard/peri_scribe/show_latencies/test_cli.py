"""CLI offsets and OSC output work with synthetic data and a frozen current clock."""

from __future__ import annotations

import base64
import dataclasses
import datetime
import pathlib
import struct
import unittest.mock

import click
import click.testing
import pytest
import time_machine

import peri_scribe.main
import peri_scribe.show_latencies.cli
import peri_scribe.show_latencies.perimeters
import peri_scribe.show_latencies.runs
import peri_scribe.terminal_images
import svg_charts.cumulative
import tests.helpers.factories.peri_scribe.show_latencies.evidence
import tests.helpers.peri_scribe.main
from measurement_units import units


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("-7d", -604800),
        ("-0d", 0),
        ("-3h", -10800),
        ("-1w", -604800),
        ("-2m", -120),
        ("-0.5s", -0.5),
        ("-25ms", -0.025),
    ],
)
def test_relative_time_convert_accepts_one_number_and_unit(
    text: str,
    seconds: float,
) -> None:
    assert peri_scribe.show_latencies.cli.RelativeTime().convert(
        text,
        None,
        None,
    ) == datetime.timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "text",
    [
        "-3d7h",
        "3h",
        "-1y",
        "yesterday",
        "-1e3s",
        "--3h",
        "-999999999999999999999999999999999999d",
        "-1.2.3h",
    ],
)
def test_relative_time_convert_rejects_ambiguous_or_unrepresentable_values(
    text: str,
) -> None:
    with pytest.raises(click.BadParameter, match="one nonpositive offset"):
        peri_scribe.show_latencies.cli.RelativeTime().convert(text, None, None)


def test_inline_image_round_trips_png_without_touching_disk() -> None:
    payload = b"\x89PNG\r\n\x1a\nhello"
    result = peri_scribe.show_latencies.cli.inline_image(payload)
    header, encoded = result.removesuffix("\a").split(":", 1)
    assert header.startswith("\033]1337;File=")
    assert "inline=1;width=1000px;height=768px;preserveAspectRatio=1" in header
    assert f"size={len(payload)}" in header
    assert base64.b64decode(encoded) == payload


def test_show_latencies_defaults_to_last_week_and_only_writes_terminal_image(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = unittest.mock.Mock(return_value=b"image")
    monkeypatch.setattr(peri_scribe.show_latencies.cli, "render", renderer)
    monkeypatch.chdir(tmp_path)
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW,
        tick=False,
    ):
        result = runner.invoke(peri_scribe.main.cli, ["show-latencies"])
    assert result.exit_code == 0, result.output
    directory, window = renderer.call_args.args
    assert directory == tmp_path / "data/2026"
    assert (
        window.start
        == tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
        - datetime.timedelta(days=7)
    )
    assert window.end == tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
    assert (
        result.stdout
        == "\r" + peri_scribe.show_latencies.cli.inline_image(b"image") + "\n"
    )
    assert not directory.exists()


def test_show_latencies_uses_terminal_display_dimensions(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        peri_scribe.show_latencies.cli,
        "render",
        unittest.mock.Mock(return_value=b"image"),
    )
    monkeypatch.setattr(
        peri_scribe.terminal_images,
        "display_dimensions",
        unittest.mock.Mock(return_value=("99", "39")),
    )
    result = runner.invoke(peri_scribe.main.cli, ["show-latencies"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("\r\x1b]1337;File=")
    assert "width=99;height=39;preserveAspectRatio=1:" in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [["--start", "-1h", "--end", "-2h"], ["--start=-0d"], ["--start", "-3d7h"]],
)
def test_show_latencies_rejects_invalid_bounds(
    runner: click.testing.CliRunner,
    arguments: list[str],
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["show-latencies", *arguments])
    assert (
        result.exit_code == tests.helpers.peri_scribe.main.CLICK_USAGE_ERROR_EXIT_CODE
    )
    assert not result.stdout


def test_show_latencies_renders_png_from_archive_and_current_log(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "logs/2026-08.jsonl.zst",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -86400,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                -86390,
                duration={"value": 10, "units": "second"},
            ),
        ],
    )
    tests.helpers.factories.peri_scribe.show_latencies.evidence.write_log(
        tmp_path / "logs/2026-09.jsonl",
        [
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Starting command",
                -20,
            ),
            tests.helpers.factories.peri_scribe.show_latencies.evidence.record(
                "Finished command",
                -10,
                duration={"value": 10, "units": "second"},
            ),
        ],
    )
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["show-latencies", str(tmp_path), "--start", "-3d", "--end", "-0h"],
        )
    assert result.exit_code == 0, result.output
    png = base64.b64decode(result.stdout.strip().removesuffix("\a").split(":", 1)[1])
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (1000, 768)
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_show_latencies_reports_empty_window_on_stderr(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    result = runner.invoke(peri_scribe.main.cli, ["show-latencies", str(tmp_path)])
    assert result.exit_code == 1
    assert "No completed runs" in result.stderr
    assert not result.stdout


def test_show_latencies_reports_corrupt_archive(
    runner: click.testing.CliRunner,
    tmp_path: pathlib.Path,
) -> None:
    directory = tmp_path / "logs"
    directory.mkdir()
    (directory / "2026-08.jsonl.zst").write_bytes(b"broken archive")
    with time_machine.travel(
        tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW,
        tick=False,
    ):
        result = runner.invoke(
            peri_scribe.main.cli,
            ["show-latencies", str(tmp_path)],
        )
    assert result.exit_code == 1
    assert "Cannot build performance chart" in result.stderr


@pytest.mark.parametrize("with_complete_run", [True, False])
def test_render_keeps_crossing_runs_only_for_polygon_consumption(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_complete_run: bool,
) -> None:
    crossing = dataclasses.replace(
        tests.helpers.factories.peri_scribe.show_latencies.evidence.run(5, geography=2),
        started=(
            tests.helpers.factories.peri_scribe.show_latencies.evidence.NOW
            - datetime.timedelta(seconds=5)
        ),
        duration=10 * units.seconds,
    )
    complete = tests.helpers.factories.peri_scribe.show_latencies.evidence.run(30)
    evidence = peri_scribe.show_latencies.runs.Evidence(
        runs=(crossing, complete) if with_complete_run else (crossing,),
        snapshots={},
    )
    monkeypatch.setattr(
        peri_scribe.show_latencies.runs,
        "read",
        unittest.mock.Mock(return_value=evidence),
    )
    latencies = unittest.mock.Mock(return_value=(4 * units.seconds,))
    monkeypatch.setattr(peri_scribe.show_latencies.perimeters, "latencies", latencies)
    renderer = unittest.mock.Mock(return_value=b"chart")
    monkeypatch.setattr(svg_charts.cumulative, "png", renderer)
    window = tests.helpers.factories.peri_scribe.show_latencies.evidence.WINDOW
    assert peri_scribe.show_latencies.cli.render(tmp_path, window) == b"chart"
    series = renderer.call_args.args[0]
    assert series[0].durations == ((complete.duration,) if with_complete_run else ())
    assert series[1].durations == (4 * units.seconds,)
    latencies.assert_called_once_with(tmp_path, evidence, window)

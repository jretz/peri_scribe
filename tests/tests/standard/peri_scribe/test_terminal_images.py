"""Terminal sizing preserves the width cap, aspect ratio, and interactive settings."""

from __future__ import annotations

import concurrent.futures
import io
import multiprocessing
import os
import pty
import select
import struct
import termios
import unittest.mock

import pytest

import peri_scribe.terminal_images
import tests.helpers.doubles.peri_scribe.terminal_images
from measurement_units import units


def test_display_dimensions_skips_query_in_background_process_group() -> None:
    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(
        target=tests.helpers.doubles.peri_scribe.terminal_images.isolated_background_query,
        args=(writer,),
    )
    process.start()
    writer.close()
    try:
        assert reader.poll(5), "Background sizing did not complete within its deadline"
        result = reader.recv()
    finally:
        reader.close()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join()
    assert process.exitcode == 0
    assert result == {
        "exit_status": 0,
        "dimensions": ["79", "31"],
        "settings_restored": True,
        "query_sent": False,
    }


@pytest.mark.parametrize("ending", [b"\x07", b"\x1b\\"])
@pytest.mark.parametrize("scale", [b"", b";2"])
def test_parse_cell_size_uses_logical_dimensions_on_high_density_displays(
    ending: bytes,
    scale: bytes,
) -> None:
    cell = peri_scribe.terminal_images.parse_cell_size(
        b"\x1b]1337;ReportCellSize=17.5;8.25" + scale + ending,
    )
    assert cell == peri_scribe.terminal_images.CellSize(
        width=8.25 * units.pixels,
        height=17.5 * units.pixels,
    )


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"\x1b]1337;ReportCellSize=16;8",
        b"\x1b]1337;ReportCellSize=0;8\x07",
        b"\x1b]1337;ReportCellSize=16;0\x07",
        b"\x1b]1337;ReportCellSize=" + b"9" * 400 + b";8\x07",
    ],
)
def test_parse_cell_size_rejects_unusable_reports(reply: bytes) -> None:
    assert peri_scribe.terminal_images.parse_cell_size(reply) is None


@pytest.mark.parametrize(
    ("columns", "expected"),
    [(80, ("79", "31")), (200, ("125", "48"))],
)
def test_display_dimensions_fills_available_width_up_to_display_pixel_cap(
    monkeypatch: pytest.MonkeyPatch,
    columns: int,
    expected: tuple[str, str],
) -> None:
    stream = tests.helpers.doubles.peri_scribe.terminal_images.stub_terminal(
        monkeypatch,
        (30, columns, columns * 16, 960),
        b"\x1b]1337;ReportCellSize=16;8;2\x07",
    )
    assert (
        peri_scribe.terminal_images.display_dimensions(
            stream,
            1000 * units.pixels,
            1000 / 768,
        )
        == expected
    )


def test_display_dimensions_uses_os_pixel_geometry_without_cell_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = tests.helpers.doubles.peri_scribe.terminal_images.stub_terminal(
        monkeypatch,
        (30, 80, 640, 480),
    )
    assert peri_scribe.terminal_images.display_dimensions(
        stream,
        1000 * units.pixels,
        1000 / 768,
    ) == ("79", "31")


@pytest.mark.parametrize(
    "dimensions",
    [(30, 1, 8, 480), (0, 80, 640, 480), (30, 80, 0, 480), (30, 80, 640, 0)],
)
def test_display_dimensions_falls_back_when_terminal_geometry_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: tuple[int, int, int, int],
) -> None:
    stream = tests.helpers.doubles.peri_scribe.terminal_images.stub_terminal(
        monkeypatch,
        dimensions,
    )
    assert peri_scribe.terminal_images.display_dimensions(
        stream,
        1000 * units.pixels,
        1000 / 768,
    ) == ("1000px", "768px")


def test_display_dimensions_keeps_pixel_cap_when_one_cell_exceeds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = tests.helpers.doubles.peri_scribe.terminal_images.stub_terminal(
        monkeypatch,
        (30, 80, 0, 0),
        b"\x1b]1337;ReportCellSize=16;1001\x07",
    )
    assert peri_scribe.terminal_images.display_dimensions(
        stream,
        1000 * units.pixels,
        1000 / 768,
    ) == ("1000px", "768px")


def test_display_dimensions_does_not_query_redirected_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "isatty", unittest.mock.Mock(return_value=False))
    query = unittest.mock.Mock()
    monkeypatch.setattr(peri_scribe.terminal_images, "terminal_dimensions", query)
    assert peri_scribe.terminal_images.display_dimensions(
        unittest.mock.Mock(),
        1000 * units.pixels,
        1000 / 768,
    ) == ("1000px", "768px")
    query.assert_not_called()


def test_display_dimensions_accepts_stream_without_file_descriptor() -> None:
    assert peri_scribe.terminal_images.display_dimensions(
        io.StringIO(),
        1000 * units.pixels,
        1000 / 768,
    ) == ("1000px", "768px")


def test_reported_cell_size_tolerates_unavailable_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "ttyname", unittest.mock.Mock(side_effect=OSError))
    assert peri_scribe.terminal_images.reported_cell_size(42) is None


def test_display_dimensions_queries_terminal_and_restores_input_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "tcgetpgrp", unittest.mock.Mock(return_value=os.getpgrp()))
    master, slave = pty.openpty()
    try:
        original = termios.tcgetattr(slave)
        peri_scribe.terminal_images.fcntl.ioctl(
            slave,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", 30, 80, 1280, 960),
        )
        with (
            concurrent.futures.ThreadPoolExecutor() as executor,
            os.fdopen(slave, "w", closefd=False) as output,
        ):
            response = executor.submit(
                tests.helpers.doubles.peri_scribe.terminal_images.answer_cell_query,
                master,
                b"\x1b]1337;ReportCellSize=16;8;2\x07",
            )
            assert peri_scribe.terminal_images.display_dimensions(
                output,
                1000 * units.pixels,
                1000 / 768,
            ) == ("79", "31")
            assert response.result() == b"\x1b]1337;ReportCellSize\x07"
        os.write(master, b"next command\n")
        assert os.read(slave, 128) == b"next command\n"
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)


def test_query_cell_size_restores_input_settings_after_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "tcgetpgrp", unittest.mock.Mock(return_value=os.getpgrp()))
    master, slave = pty.openpty()
    monkeypatch.setattr(
        peri_scribe.terminal_images,
        "read_cell_size",
        unittest.mock.Mock(side_effect=OSError("query failed")),
    )
    try:
        original = termios.tcgetattr(slave)
        with pytest.raises(OSError, match="query failed"):
            peri_scribe.terminal_images.query_cell_size(slave)
        os.write(master, b"next command\n")
        assert os.read(slave, 128) == b"next command\n"
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)


def test_query_cell_size_preserves_already_queued_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        select,
        "select",
        unittest.mock.Mock(return_value=([42], [], [])),
    )
    reader = unittest.mock.Mock()
    monkeypatch.setattr(peri_scribe.terminal_images, "read_cell_size", reader)
    assert peri_scribe.terminal_images.query_cell_size(42) is None
    reader.assert_not_called()


def test_query_cell_size_never_changes_background_terminal_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(select, "select", unittest.mock.Mock(return_value=([], [], [])))
    monkeypatch.setattr(
        os,
        "tcgetpgrp",
        unittest.mock.Mock(return_value=os.getpgrp() + 1),
    )
    set_mode = unittest.mock.Mock()
    monkeypatch.setattr(peri_scribe.terminal_images.tty, "setcbreak", set_mode)
    assert peri_scribe.terminal_images.query_cell_size(42) is None
    set_mode.assert_not_called()


def test_query_cell_size_preserves_unfinished_canonical_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "tcgetpgrp", unittest.mock.Mock(return_value=os.getpgrp()))
    master, slave = pty.openpty()
    try:
        original = termios.tcgetattr(slave)
        os.write(master, b"next command")
        assert not select.select([slave], [], [], 0)[0]
        assert peri_scribe.terminal_images.query_cell_size(slave) is None
        os.write(master, b"\n")
        assert select.select([slave], [], [], 1)[0]
        assert os.read(slave, 128) == b"next command\n"
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("reply", [b"", b"x" * 128, b"unrecognized\x07"])
def test_read_cell_size_ignores_incomplete_oversized_or_unrecognized_responses(
    monkeypatch: pytest.MonkeyPatch,
    reply: bytes,
) -> None:
    writer = tests.helpers.doubles.peri_scribe.terminal_images.stub_cell_reply(
        monkeypatch,
        reply,
    )
    assert peri_scribe.terminal_images.read_cell_size(42) is None
    writer.assert_called_once_with(42, b"\x1b]1337;ReportCellSize\x07")


def test_read_cell_size_stops_when_no_response_arrives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.terminal_images.stub_cell_reply(monkeypatch, b"")
    monkeypatch.setattr(select, "select", unittest.mock.Mock(return_value=([], [], [])))
    assert peri_scribe.terminal_images.read_cell_size(42) is None


def test_read_cell_size_bounds_wait_even_when_partial_response_keeps_arriving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tests.helpers.doubles.peri_scribe.terminal_images.stub_cell_reply(monkeypatch, b"x")
    monkeypatch.setattr(
        peri_scribe.terminal_images.time,
        "monotonic",
        unittest.mock.Mock(side_effect=[0, 0, 1]),
    )
    assert peri_scribe.terminal_images.read_cell_size(42) is None

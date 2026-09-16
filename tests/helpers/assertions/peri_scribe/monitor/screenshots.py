"""Compare exported ANSI with composed text and background cells."""

import re
import typing

import rich.ansi
import rich.cells
import rich.style


if typing.TYPE_CHECKING:
    import peri_scribe.monitor.screenshots


def assert_screen_matches_snapshot(
    screen: peri_scribe.monitor.screenshots.SnapshotScreen,
) -> None:
    """Painted cells remain authoritative while footer bindings are being rebuilt.

    Args:
        screen: The mounted screen whose screenshot must preserve terminal cells.
    """
    expected_rows = screen.snapshot_rows()
    content = screen.export_snapshot()
    rows = list(rich.ansi.AnsiDecoder().decode(content.rstrip("\n")))
    assert len(rows) == screen.app.size.height
    assert all(rich.cells.cell_len(row.plain) == screen.app.size.width for row in rows)
    assert "PeriScribe monitor" in rows[0].plain
    assert "\x1b[" in content
    assert "\x1b" not in re.sub(r"\x1b\[[0-9;]*m", "", content)
    for row, expected_row in zip(rows, expected_rows, strict=True):
        assert row.plain == expected_row.text
        offset = 0
        for segment in expected_row:
            expected = segment.style or rich.style.Style.null()
            for _ in segment.text:
                actual = row.get_style_at_offset(screen.app.console, offset)
                assert actual.color == expected.color
                assert actual.bgcolor == expected.bgcolor
                assert bool(actual.bold) == bool(expected.bold)
                assert bool(actual.reverse) == bool(expected.reverse)
                offset += 1

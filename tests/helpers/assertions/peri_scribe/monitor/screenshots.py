"""Compare a screenshot with its live screen before asynchronous redraws intervene."""

import re
import typing

import rich.ansi
import rich.cells


if typing.TYPE_CHECKING:
    import peri_scribe.monitor.screenshots


def assert_screen_matches_snapshot(
    screen: peri_scribe.monitor.screenshots.SnapshotScreen,
) -> None:
    """Keep capture and style inspection in the same uninterrupted UI callback.

    Args:
        screen: The mounted screen whose screenshot must preserve terminal cells.
    """
    content = screen.export_snapshot()
    rows = list(rich.ansi.AnsiDecoder().decode(content.rstrip("\n")))
    assert len(rows) == screen.app.size.height
    assert all(rich.cells.cell_len(row.plain) == screen.app.size.width for row in rows)
    assert "PeriScribe monitor" in rows[0].plain
    assert "\x1b[" in content
    assert "\x1b" not in re.sub(r"\x1b\[[0-9;]*m", "", content)
    for y, row in enumerate(rows):
        x = 0
        for offset, character in enumerate(row.plain):
            actual = row.get_style_at_offset(screen.app.console, offset)
            expected = screen.get_style_at(x, y)
            assert actual.color == expected.color
            assert actual.bgcolor == expected.bgcolor
            assert bool(actual.bold) == bool(expected.bold)
            assert bool(actual.reverse) == bool(expected.reverse)
            x += rich.cells.cell_len(character)

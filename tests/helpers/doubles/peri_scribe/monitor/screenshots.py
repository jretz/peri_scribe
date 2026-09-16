"""Capture the footer between removing its bindings and mounting their replacements."""

import collections.abc
import typing

import tests.helpers.assertions.peri_scribe.monitor.screenshots


if typing.TYPE_CHECKING:
    import textual.widget

    import peri_scribe.monitor.screenshots


def mount_after_snapshot_check(
    screen: peri_scribe.monitor.screenshots.SnapshotScreen,
    mount: collections.abc.Callable[
        [collections.abc.Iterable[textual.widget.Widget]],
        textual.widget.AwaitMount,
    ],
    widgets: collections.abc.Iterable[textual.widget.Widget],
) -> textual.widget.AwaitMount:
    """Exercise the transient footer layout without relying on scheduler timing.

    Args:
        screen: The monitor screen whose snapshot must retain its rendered styles.
        mount: The footer's ordinary mounting operation.
        widgets: The replacement bindings ready to be mounted.

    Returns:
        The footer's ordinary mount completion after checking its transient snapshot.
    """
    tests.helpers.assertions.peri_scribe.monitor.screenshots.assert_screen_matches_snapshot(
        screen,
    )
    return mount(widgets)

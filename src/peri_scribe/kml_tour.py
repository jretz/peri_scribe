"""Building a fire's progression tour.

A tour replays the fire's growth rings oldest first. These helpers name the tour's
placemarks, choose its playback rate, and emit the animated visibility updates that
reveal each ring in turn.
"""

from __future__ import annotations

import datetime
import typing

import peri_scribe.kml_template
import peri_scribe.perimeter_progression


if typing.TYPE_CHECKING:
    import simplekml


# A tour advances through fire time at one second of playback per day, and holds the
# final frame for two seconds. Fires spanning more than MAX_TOUR_PLAYBACK_IN_SECONDS
# days play faster so the whole progression takes about that long instead of one second
# per day.
TOUR_PLAYBACK_SECONDS_PER_DAY = 1.0
MAX_TOUR_PLAYBACK_IN_SECONDS = 5.0
FINAL_TOUR_WAIT_IN_SECONDS = 1.0

MAPPING_NAME = "Perimeter"
UNKNOWN_MAPPING_NAME = "Unknown Mapping"

PROGRESSION_TOUR_NAME = "Progression"


def time_label(observation_time: datetime.datetime | None) -> str | None:
    """Return the California-time label for *observation_time*, or None.

    The label reads like ``08/05 13:30``: month/day, then a 24-hour clock
    time with leading zeros and no am/pm marker.

    Args:
        observation_time: The observation time as an aware UTC datetime, or None.

    Returns:
        The label, or None when *observation_time* is None.
    """
    if observation_time is None:
        return None
    pacific_time = observation_time.astimezone(
        peri_scribe.perimeter_progression.CALIFORNIA_TIME_ZONE,
    )
    return f"{pacific_time:%m/%d %H:%M}"


def interior_placemark_name(observation_time: datetime.datetime | None) -> str:
    """Return the filled-interior placemark name for *observation_time*.

    Args:
        observation_time: The observation time of the latest perimeter, or None.

    Returns:
        The placemark name, ``<date> Interior`` when the time is known and
        ``Interior`` otherwise.
    """
    label = time_label(observation_time)
    if label is None:
        return peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name
    return f"{label} {peri_scribe.kml_template.FILLED_PERIMETER_TEMPLATE.name}"


def mapping_placemark_name(observation_time: datetime.datetime | None) -> str:
    """Return the outline placemark name for *observation_time*.

    Args:
        observation_time: The observation time of the perimeter, or None.

    Returns:
        The placemark name, ``<date> Perimeter`` when the time is known and
        ``Unknown Mapping`` otherwise.
    """
    label = time_label(observation_time)
    if label is None:
        return UNKNOWN_MAPPING_NAME
    return f"{label} {MAPPING_NAME}"


def interior_ring_id(folder: simplekml.Folder, index: int) -> str:
    """Return the placemark id for *folder*'s interior ring at *index*.

    The tour's animated updates target these ids, so each one must be unique across the
    document; the folder's own unique id keeps one fire's ring ids apart from every
    other fire's.

    Args:
        folder: The fire folder that holds the ring.
        index: The ring's position, oldest first.

    Returns:
        The ring's placemark id.
    """
    return f"progression-ring-{folder.id}-{index}"


def tour_seconds_per_day(
    ring_times: typing.Sequence[datetime.datetime | None],
) -> float:
    """Return the tour's playback rate, in seconds per day of fire time.

    Fires spanning at most MAX_TOUR_PLAYBACK_IN_SECONDS days play at
    TOUR_PLAYBACK_SECONDS_PER_DAY so every day stays visible; longer fires play
    proportionally faster so the whole progression takes about
    MAX_TOUR_PLAYBACK_IN_SECONDS.

    Args:
        ring_times: Each interior ring's observation time, oldest first.

    Returns:
        The playback rate in seconds per day.
    """
    observed_times = [time for time in ring_times if time is not None]
    if not observed_times:
        return TOUR_PLAYBACK_SECONDS_PER_DAY
    total_in_days = (observed_times[-1] - observed_times[0]).total_seconds() / 86_400
    if total_in_days <= MAX_TOUR_PLAYBACK_IN_SECONDS:
        return TOUR_PLAYBACK_SECONDS_PER_DAY
    return MAX_TOUR_PLAYBACK_IN_SECONDS / total_in_days


def tour_wait_in_seconds(
    earlier: datetime.datetime | None,
    later: datetime.datetime | None,
    seconds_per_day: float,
) -> float:
    """Return the tour wait, in seconds, between two ring observations.

    The wait is the number of days that separate the two observations times the tour's
    playback rate. A missing observation time yields no wait, because there is no time
    to advance through.

    Args:
        earlier: The earlier ring's observation time, or None.
        later: The later ring's observation time, or None.
        seconds_per_day: The tour's playback rate in seconds per day.

    Returns:
        The wait in seconds.
    """
    if earlier is None or later is None:
        return 0.0
    in_days = (later - earlier).total_seconds() / 86_400
    return seconds_per_day * in_days


def visibility_change(
    ring_ids: typing.Sequence[str],
    shown_through: int,
) -> str:
    """Return the update text that reveals rings through *shown_through*.

    Each ring through *shown_through* is shown and every later ring is hidden, so each
    step names the whole interior state rather than only the one ring it reveals.

    Args:
        ring_ids: Every interior ring's placemark id, oldest first.
        shown_through: The index of the newest ring to show.

    Returns:
        The ``<Placemark targetId=...>`` visibility text for every ring.
    """
    updates: list[str] = []
    for index, ring_id in enumerate(ring_ids):
        visibility = "1" if index <= shown_through else "0"
        updates.append(
            f'<Placemark targetId="{ring_id}">'
            f"<visibility>{visibility}</visibility>"
            "</Placemark>",
        )
    return "".join(updates)


def progression_tour(
    folder: simplekml.Folder,
    ring_times: typing.Sequence[datetime.datetime | None],
) -> None:
    """Add the "Progression" tour to *folder*.

    The tour shows the innermost ring alone, then waits for the fire time between
    observations at the tour's playback rate before revealing each next ring, and holds
    the final frame for two seconds. The playback rate is one second per day for fires
    spanning at most MAX_TOUR_PLAYBACK_IN_SECONDS days, and faster for longer fires so
    the whole progression takes about MAX_TOUR_PLAYBACK_IN_SECONDS. It is added before
    the folder's placemarks so it leads them.

    Args:
        folder: The fire folder that holds the tour.
        ring_times: Each interior ring's observation time, oldest first.
    """
    ring_ids = [interior_ring_id(folder, index) for index in range(len(ring_times))]
    seconds_per_day = tour_seconds_per_day(ring_times)
    tour = folder.newgxtour(name=PROGRESSION_TOUR_NAME)
    playlist = tour.newgxplaylist()
    for index, ring_time in enumerate(ring_times):
        playlist.newgxanimatedupdate().update.change = visibility_change(
            ring_ids,
            index,
        )
        if index + 1 < len(ring_times):
            wait_in_seconds = tour_wait_in_seconds(
                ring_time,
                ring_times[index + 1],
                seconds_per_day,
            )
        else:
            wait_in_seconds = FINAL_TOUR_WAIT_IN_SECONDS
        playlist.newgxwait(gxduration=wait_in_seconds)


def assign_placemark_id(
    placemark: simplekml.Polygon | simplekml.MultiGeometry,
    placemark_id: str,
) -> None:
    """Assign *placemark* the stable id *placemark_id*.

    The tour's animated updates reference the interior rings by their placemark ids, and
    simplekml offers no public way to choose one, so the id is set directly.

    Args:
        placemark: The polygon or multi-geometry placemark to identify.
        placemark_id: The id to assign.
    """
    placemark.placemark._id = placemark_id  # ruff: ignore[private-member-access]

"""Building a fire's progression tour.

A tour replays the fire's growth rings oldest first. These helpers name the tour's
placemarks, choose its playback rate, and emit the animated visibility updates that
reveal each ring in turn.
"""

from __future__ import annotations

import datetime
import typing

import peri_scribe.kml.geometry
import peri_scribe.kml.styles
import peri_scribe.perimeters.progression
from peri_scribe.units import units


if typing.TYPE_CHECKING:
    import pint


# A tour advances through fire time at one second of playback per day, and holds the
# final frame for two seconds. Fires spanning more than the base-rate span play faster
# so the whole progression takes about MAX_TOUR_PLAYBACK instead of one second per day.
TOUR_PLAYBACK_RATE = 1.0
MAX_TOUR_PLAYBACK = 5.0 * units.seconds
FINAL_TOUR_WAIT = 1.0 * units.seconds

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

    Examples:
        >>> time_label(datetime.datetime(2025, 8, 5, 20, 30, tzinfo=datetime.UTC))
        '08/05 13:30'
    """
    if observation_time is None:
        return None
    pacific_time = observation_time.astimezone(
        peri_scribe.perimeters.progression.CALIFORNIA_TIME_ZONE,
    )
    return f"{pacific_time:%m/%d %H:%M}"


def interior_placemark_name(observation_time: datetime.datetime | None) -> str:
    """Return the filled-interior placemark name for *observation_time*.

    Args:
        observation_time: The observation time of the latest perimeter, or None.

    Returns:
        The placemark name, ``<date> Interior`` when the time is known and
        ``Interior`` otherwise.

    Examples:
        >>> interior_placemark_name(None)
        'Interior'
    """
    label = time_label(observation_time)
    if label is None:
        return peri_scribe.kml.styles.FILLED_PERIMETER_NAME
    return f"{label} {peri_scribe.kml.styles.FILLED_PERIMETER_NAME}"


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


def interior_ring_id(folder_id: str, index: int) -> str:
    """Return the placemark id for the ring at *index* in *folder_id*.

    The tour's animated updates target these ids, so each one must be unique across the
    document; the folder's own unique id keeps one fire's ring ids apart from every
    other fire's.

    Args:
        folder_id: The unique id of the folder that holds the ring.
        index: The ring's position, oldest first.

    Returns:
        The ring's placemark id.

    Examples:
        >>> interior_ring_id("fire-1", 2)
        'progression-ring-fire-1-2'
    """
    return f"progression-ring-{folder_id}-{index}"


def tour_playback_rate(ring_times: typing.Sequence[datetime.datetime | None]) -> float:
    """Return the tour's playback rate, in seconds per day of fire time.

    Fires spanning at most the base-rate span play at TOUR_PLAYBACK_RATE so every day
    stays visible; longer fires play proportionally faster so the whole progression
    takes about MAX_TOUR_PLAYBACK. The rate is a plain number because pint reduces a
    seconds-per-day ratio to dimensionless.

    Args:
        ring_times: Each interior ring's observation time, oldest first.

    Returns:
        The playback rate in seconds per day.

    Examples:
        >>> tour_playback_rate([])
        1.0
    """
    observed_times = [time for time in ring_times if time is not None]
    if not observed_times:
        return TOUR_PLAYBACK_RATE
    span = observed_times[-1] - observed_times[0]
    span_in_days = span / datetime.timedelta(days=1)
    base_rate_span_in_days = MAX_TOUR_PLAYBACK.m_as("seconds") / TOUR_PLAYBACK_RATE
    if span_in_days <= base_rate_span_in_days:
        return TOUR_PLAYBACK_RATE
    return MAX_TOUR_PLAYBACK.m_as("seconds") / span_in_days


def tour_wait(
    earlier: datetime.datetime | None,
    later: datetime.datetime | None,
    playback_rate: float,
) -> pint.Quantity[float]:
    """Return the tour wait between two ring observations.

    The wait is the number of days that separate the two observations times the tour's
    playback rate. A missing observation time yields no wait, because there is no time
    to advance through.

    Args:
        earlier: The earlier ring's observation time, or None.
        later: The later ring's observation time, or None.
        playback_rate: The tour's playback rate in seconds per day.

    Returns:
        The wait.
    """
    if earlier is None or later is None:
        return 0 * units.seconds
    gap = later - earlier
    gap_in_days = gap / datetime.timedelta(days=1)
    return gap_in_days * playback_rate * units.seconds


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
    writer: peri_scribe.kml.geometry.KmlWriter,
    folder_id: str,
    ring_times: typing.Sequence[datetime.datetime | None],
    *,
    visible: bool = True,
) -> None:
    """Append the "Progression" tour to *writer*.

    The tour shows the innermost ring alone, then waits for the fire time between
    observations at the tour's playback rate before revealing each next ring, and holds
    the final frame for two seconds. The playback rate is one second per day for fires
    spanning at most the base-rate span, and faster for longer fires so the whole
    progression takes about MAX_TOUR_PLAYBACK. Callers place it where they want it in
    the folder; it targets the rings by their placemark ids, so the rings' listing order
    does not affect it.

    Args:
        writer: The writer to append to.
        folder_id: The fire folder's unique id, used to name the tour's targets.
        ring_times: Each interior ring's observation time, oldest first.
        visible: Whether the tour is visible.
    """
    ring_ids = [interior_ring_id(folder_id, index) for index in range(len(ring_times))]
    playback_rate = tour_playback_rate(ring_times)
    parts = writer.parts
    parts.append("<gx:Tour>")
    if not visible:
        parts.append("<visibility>0</visibility>")
    parts.append(f"<name>{PROGRESSION_TOUR_NAME}</name><gx:Playlist>")
    for index, ring_time in enumerate(ring_times):
        parts.append(
            "<gx:AnimatedUpdate><Update><targetHref></targetHref><Change>",
        )
        parts.append(visibility_change(ring_ids, index))
        parts.append("</Change></Update></gx:AnimatedUpdate>")
        if index + 1 < len(ring_times):
            wait = tour_wait(ring_time, ring_times[index + 1], playback_rate)
        else:
            wait = FINAL_TOUR_WAIT
        parts.append(
            f"<gx:Wait><gx:duration>{wait.m_as('second')}</gx:duration></gx:Wait>",
        )
    parts.append("</gx:Playlist></gx:Tour>")

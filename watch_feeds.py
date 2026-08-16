"""Watch the configured feeds for updates and log when their watermarks change.

For each configured ArcGIS feed this script keeps an in-memory watermark built
from three change-detection signals observed with tiny requests:

- ``Last-Modified`` and ``ETag`` response headers from a cache-busted ``HEAD``
  request on the layer metadata URL. ArcGIS mirrors the layer's authoritative
  ``editingInfo.dataLastEditDate`` in the ``Last-Modified`` header, and the
  ``ETag`` changes whenever the data changes. The cache-buster query parameter
  (``_cb``) forces a fresh origin response, avoiding stale CDN replies within
  the service's ``max-age`` window.
- The feature count from a ``returnCountOnly=true`` query, as a secondary
  signal that also catches data changes not reflected in the headers.

The watermark and the observed update times live in memory only, so every
run starts by establishing a baseline for each feed and then logs whenever a
later check observes a different watermark. Each detected change records the
time it was observed in UTC, and a combined 24-bin histogram of every feed's
update times is written to a PNG file in the project root, overwriting the
previous image. Histogram bins use the local time of the running machine,
as do the timestamps on all log lines.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import pathlib
import time
from typing import TYPE_CHECKING

import matplotlib as mpl
import pandas as pd
import requests
import structlog


mpl.use("Agg")

import matplotlib.pyplot as plt
import seaborn as sns

import peri_scribe.models
import peri_scribe.output


if TYPE_CHECKING:
    from collections.abc import Sequence


logger = structlog.get_logger()

HISTOGRAM_FILENAME = "feed_update_histogram.png"
HISTOGRAM_PATH = pathlib.Path(__file__).parent / HISTOGRAM_FILENAME
HISTOGRAM_BAR_COLORS = ("#FF0000", "#00FF00", "#0000FF")
HOURS_PER_DAY = 24
MINIMUM_INTERVAL_SECONDS = 1
REQUEST_TIMEOUT_SECONDS = 30
USER_AGENT = "peri_scribe-watcher/0.1"


@dataclasses.dataclass(frozen=True, kw_only=True)
class Watermark:
    """The change-detection signals observed for one feed."""

    last_modified: str | None
    etag: str | None
    count: int | None

    def changed_components(self, previous: Watermark) -> tuple[str, ...]:
        """Return the names of the signals that differ from *previous*.

        Returns:
            The names of the signals that differ from *previous*.
        """
        components: list[str] = []
        if self.last_modified != previous.last_modified:
            components.append("last_modified")
        if self.etag != previous.etag:
            components.append("etag")
        if self.count != previous.count:
            components.append("count")
        return tuple(components)


def observe_count(url: str) -> int | None:
    """Return the feature count for the layer at *url*.

    Returns:
        The feature count for the layer at *url*, or None when the query fails
        or the response carries no count.
    """
    query_url = f"{url}/query"
    parameters = {"where": "1=1", "returnCountOnly": "true", "f": "json"}
    try:
        response = requests.get(
            query_url,
            params=parameters,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.exceptions.RequestException, ValueError) as error:
        logger.warning(
            "Count query failed",
            url=query_url,
            error=str(error),
        )
        return None
    if not isinstance(payload, dict) or "count" not in payload:
        logger.warning(
            "Count query returned no count",
            url=query_url,
            response=payload,
        )
        return None
    return payload["count"]


def observe_watermark(url: str) -> Watermark | None:
    """Observe the current watermark for the layer at *url*.

    Returns:
        The observed watermark for the layer at *url*, or None when a request
        fails.
    """
    parameters = {"f": "json", "_cb": time.time_ns()}
    try:
        response = requests.head(
            url,
            params=parameters,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        logger.warning(
            "Watermark check failed",
            url=url,
            error=str(error),
        )
        return None
    count = observe_count(url)
    if count is None:
        return None
    return Watermark(
        last_modified=response.headers.get("Last-Modified"),
        etag=response.headers.get("ETag"),
        count=count,
    )


def count_updates_by_hour(update_times: Sequence[datetime.datetime]) -> list[int]:
    """Count update times per hour of the day in the machine's local time.

    Update times are stored in UTC and converted to the local time of the
    running machine before binning.

    Returns:
        A list of 24 counts, one per hour of the day, in hour order.
    """
    counts = [0] * HOURS_PER_DAY
    for update_time in update_times:
        hour = update_time.astimezone().hour
        counts[hour] += 1
    return counts


def write_histogram_png(update_times: dict[str, list[datetime.datetime]]) -> None:
    """Write the update-time histogram for all feeds to the PNG file.

    The histogram has one bin per hour of the day in the local time of the
    running machine, with each feed drawn as an adjacent bar within every
    bin. The chart uses a dark background with light text, and the PNG file
    is overwritten on every call.

    Args:
        update_times: The observed update times, keyed by feed name.
    """
    if not update_times:
        return
    rows: list[dict[str, int | str]] = []
    for feed_name, times in update_times.items():
        for hour, count in enumerate(count_updates_by_hour(times)):
            rows.append({"feed": feed_name, "hour": hour, "count": count})
    counts_data_frame = pd.DataFrame(rows)
    with plt.style.context("dark_background"):
        figure, plot = plt.subplots(figsize=(10, 10), constrained_layout=True)
        sns.barplot(
            data=counts_data_frame,
            x="count",
            y="hour",
            hue="feed",
            palette=HISTOGRAM_BAR_COLORS,
            saturation=1,
            errorbar=None,
            orient="h",
            ax=plot,
        )
        plot.set_xlabel("Updates")
        plot.set_ylabel("Hour of day")
        plot.set_title("Feed update times by hour of day")
        plot.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.12),
            ncol=1,
            frameon=False,
        )
        figure.savefig(HISTOGRAM_PATH)
        plt.close(figure)


def check_source(
    feed_name: str,
    url: str,
    previous_watermark: Watermark | None,
    update_times: dict[str, list[datetime.datetime]],
) -> Watermark | None:
    """Check *url* for changes, log any, and return the watermark to keep.

    The first successful observation for a feed establishes its baseline
    without logging a change. A failed observation keeps the previous
    watermark so that a transient error does not masquerade as a change.
    A detected change appends the current UTC time to *update_times* and
    writes the combined 24-hour histogram of all feeds' update times (in the
    local time of the running machine) to the PNG file.

    Returns:
        The watermark to keep in memory for the next check of this feed.
    """
    current_watermark = observe_watermark(url)
    if current_watermark is None:
        return previous_watermark
    if previous_watermark is None:
        logger.info(
            "Watermark baseline established",
            feed=feed_name,
            last_modified=current_watermark.last_modified,
            etag=current_watermark.etag,
            count=current_watermark.count,
        )
        return current_watermark
    changed_components = current_watermark.changed_components(previous_watermark)
    if changed_components:
        logger.info(
            "Watermark changed",
            feed=feed_name,
            changed_components=", ".join(changed_components),
            previous_last_modified=previous_watermark.last_modified,
            last_modified=current_watermark.last_modified,
            previous_etag=previous_watermark.etag,
            etag=current_watermark.etag,
            previous_count=previous_watermark.count,
            count=current_watermark.count,
        )
        update_times[feed_name].append(datetime.datetime.now(datetime.UTC))
        write_histogram_png(update_times)
        return current_watermark
    logger.debug("Watermark unchanged", feed=feed_name)
    return current_watermark


def run_monitor(sources: list[tuple[str, str]], interval_seconds: int) -> None:
    """Check every source once per interval, forever, keeping state in RAM."""
    watermarks: dict[str, Watermark | None] = {}
    update_times: dict[str, list[datetime.datetime]] = {
        feed_name: [] for feed_name, _ in sources
    }
    logger.info(
        "Watching feeds for updates",
        feed_count=len(sources),
        interval_seconds=interval_seconds,
    )
    while True:
        for feed_name, url in sources:
            watermarks[feed_name] = check_source(
                feed_name,
                url,
                watermarks.get(feed_name),
                update_times,
            )
        time.sleep(interval_seconds)


def parse_arguments() -> argparse.Namespace:
    """Parse the command line arguments.

    Returns:
        The parsed command line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Watch configured feeds for updates and log watermark changes.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Seconds between update checks (default: 60).",
    )
    parser.add_argument(
        "--log-level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
        help="Logging level (default: info).",
    )
    arguments = parser.parse_args()
    if arguments.interval_seconds < MINIMUM_INTERVAL_SECONDS:
        parser.error(f"interval-seconds must be at least {MINIMUM_INTERVAL_SECONDS}")
    return arguments


def main() -> None:
    """Run the feed watermark monitor until interrupted."""
    arguments = parse_arguments()
    peri_scribe.output.configure_logging(arguments.log_level)
    sns.set_theme()
    sources = [(feed.name, feed.url) for feed in peri_scribe.models.FEEDS]
    try:
        run_monitor(sources, arguments.interval_seconds)
    except KeyboardInterrupt:
        logger.info("Stopping feed monitor")


if __name__ == "__main__":
    main()

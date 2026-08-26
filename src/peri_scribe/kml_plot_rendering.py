"""Rendering every fire's plots in one shared process pool.

Each pool worker builds its renderer once and clears the figure between plots, so the
per-plot work is only drawing and encoding. A fire's plot is skipped when none of its
lines span enough observation times.
"""

from __future__ import annotations

import contextlib
import dataclasses
import multiprocessing
import os
import re

import peri_scribe.kml_plot_data
import peri_scribe.kml_plot_drawing


# Pool workers lower their scheduling priority by this niceness increment, as the
# ``nice`` command does, so the batch rendering yields the machine to other work while
# it runs.
WORKER_NICENESS_INCREMENT = 10


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotImage:
    """One rendered plot: its filename and PNG bytes."""

    filename: str
    content: bytes


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotRequest:
    """One plot ready to render: which fire it belongs to and its lines.

    A plot is only requested after its lines survived the minimum-observation filter, so
    every request produces exactly one image. The y-axis label is per-plot data; the
    shared setup a worker reuses holds no per-type state.
    """

    fire_index: int
    filename_prefix: str
    filename_suffix: str
    y_axis_label: str
    series: tuple[peri_scribe.kml_plot_data.PlotSeries, ...]


# The rendering setup each pool worker reuses for every plot it draws. The pool
# initializer appends one renderer per worker; the workers share it across the pool's
# plots by clearing the figure between them. The parent process never renders, so its
# list stays empty.
worker_renderers: list[peri_scribe.kml_plot_drawing.PlotRenderer] = []


def initialize_worker() -> None:
    """Create the renderer a plot pool worker reuses for every plot it draws.

    This runs once per worker process when the pool starts. The renderer holds the
    figure, canvas, and buffer the worker clears between plots; the y-axis label is
    per-plot data and travels with each request instead.
    """
    # Set niceness when possible to keep the machine responsive while the pool works.
    # Some platforms (e.g., Windows) do not have os.nice at all (AttributeError) and
    # sometimes sandboxes (e.g., used with coding agents) prevent changing niceness
    # (OSError), so ignore those errors as they don't change functionality.
    with contextlib.suppress(AttributeError, OSError):
        os.nice(WORKER_NICENESS_INCREMENT)
    worker_renderers.append(peri_scribe.kml_plot_drawing.create_plot_renderer())


def render_plot_request(request: PlotRequest) -> PlotImage:
    """Render *request* on this worker's shared renderer.

    A pool worker calls this once per plot; the worker's renderer was created by the
    pool initializer.

    Args:
        request: The plot to render.

    Returns:
        The rendered image.

    Raises:
        RuntimeError: When the worker's renderer has not been created.
    """
    renderer = worker_renderers[0] if worker_renderers else None
    if renderer is None:
        message = "a plot pool worker must create its renderer before rendering"
        raise RuntimeError(message)
    return PlotImage(
        filename=plot_filename(
            request.filename_prefix,
            request.filename_suffix,
        ),
        content=peri_scribe.kml_plot_drawing.draw_plot(
            renderer,
            request.series,
            y_axis_label=request.y_axis_label,
        ),
    )


def worker_count_for(task_count: int) -> int:
    """Return the number of workers the plot pool should use.

    A pool never needs more workers than it has plots to render, and never more than the
    machine has cores.

    Args:
        task_count: The number of plots the pool will render.

    Returns:
        The number of workers, at least one.
    """
    return max(1, min(task_count, os.cpu_count() or 1))


def plot_image_bundles(
    fire_bundles: tuple[
        tuple[str, tuple[peri_scribe.kml_plot_data.FirePlot, ...]],
        ...,
    ],
) -> tuple[tuple[PlotImage, ...], ...]:
    """Render every fire's plots in parallel with one shared pool.

    Every worker in the pool creates its figure, canvas, and output buffer once and
    clears the figure between plots, so the per-plot work is only drawing and encoding.
    A fire's plot is skipped when none of its lines span enough observation times.

    Args:
        fire_bundles: Each fire's filename prefix and its plots, in fire order.

    Returns:
        Each fire's rendered images, in the input fire order and in each fire's
        plot order.
    """
    requests: list[PlotRequest] = []
    for fire_index, (filename_prefix, plots) in enumerate(fire_bundles):
        for plot in plots:
            series = peri_scribe.kml_plot_data.retained_series(plot.series)
            if not series:
                continue
            requests.append(
                PlotRequest(
                    fire_index=fire_index,
                    filename_prefix=filename_prefix,
                    filename_suffix=plot.filename_suffix,
                    y_axis_label=plot.y_axis_label,
                    series=series,
                ),
            )
    images_by_fire: list[list[PlotImage]] = [[] for _fire in fire_bundles]
    if not requests:
        return tuple(tuple(images) for images in images_by_fire)
    with multiprocessing.Pool(
        worker_count_for(len(requests)),
        initializer=initialize_worker,
    ) as pool:
        results = pool.map(render_plot_request, requests)
    for request, image in zip(requests, results, strict=True):
        images_by_fire[request.fire_index].append(image)
    return tuple(tuple(images) for images in images_by_fire)


def plot_filename(filename_prefix: str, filename_suffix: str) -> str:
    """Return the image filename for *filename_suffix* under *filename_prefix*.

    Args:
        filename_prefix: The fire's unique filename prefix.
        filename_suffix: The plot's suffix, like ``area``.

    Returns:
        The filename, like ``2026-cabug-000001-area.png``.
    """
    image_format = peri_scribe.kml_plot_drawing.IMAGE_FORMAT
    return f"{filename_prefix}-{filename_suffix}.{image_format}"


def filename_prefix(identifier: str | None, name: str) -> str:
    """Return a filesystem-safe filename prefix for a fire.

    The canonical identifier is preferred and is already a unique token; a fire without
    one uses its name. Either way, every non-alphanumeric run collapses to a hyphen so
    the prefix is safe to use in a filename and an HTML image source.

    Args:
        identifier: The fire's canonical identifier, or None.
        name: The fire's name.

    Returns:
        The filename prefix.
    """
    value = identifier if identifier is not None else name
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "fire"

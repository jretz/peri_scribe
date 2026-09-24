"""Rendering every fire's plots.

A fire's plot is skipped when none of its lines span enough observation times. Rendering
is pure string assembly, so the plots are drawn inline: the whole season renders in well
under a second.
"""

from __future__ import annotations

import dataclasses
import hashlib
import locale
import os
import re
import time
import typing

import defusedxml.common
import defusedxml.ElementTree

import peri_scribe.kml.plot_data
import spatial_data.cache_values
import spatial_data.product_cache
import svg_charts.models
import svg_charts.svg
import svg_charts.time_series


PLOT_NAMESPACE = "chart-svg-v1"


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotImage:
    """One rendered plot: its filename and its SVG bytes."""

    filename: str
    content: bytes


@dataclasses.dataclass(frozen=True, kw_only=True)
class PlotRequest:
    """One plot ready to render: which fire it belongs to and its lines.

    A plot is only requested after its lines survived the minimum-observation filter, so
    every request produces exactly one image.
    """

    fire_index: int
    filename_prefix: str
    filename_suffix: str
    y_axis_label: str
    series: tuple[svg_charts.models.PlotSeries, ...]


def render_plot_request(request: PlotRequest) -> PlotImage:
    """Render *request*.

    Args:
        request: The plot to render.

    Returns:
        The rendered image.
    """
    key = plot_key(request) if spatial_data.product_cache.active() else None
    content = cached_plot_content(key) if key is not None else None
    if content is None:
        content = svg_charts.time_series.draw_plot(
            request.series,
            y_axis_label=request.y_axis_label,
        )
        if key is not None:
            spatial_data.product_cache.put(PLOT_NAMESPACE, key, content)
    return PlotImage(
        filename=plot_filename(request.filename_prefix, request.filename_suffix),
        content=content,
    )


def plot_key(request: PlotRequest) -> str | None:
    """Fingerprint every drawing input while leaving filenames and bundle order live.

    Args:
        request: Complete ordered series and axis labels sent to the renderer.

    Returns:
        The input fingerprint, or None for unsupported uncached drawing inputs.
    """
    settings = tuple(
        (
            module.__name__,
            tuple(
                sorted(
                    (name, value)
                    for name, value in vars(module).items()
                    if name.isupper()
                ),
            ),
        )
        for module in (svg_charts.time_series, svg_charts.svg)
    )
    try:
        payload = spatial_data.cache_values.dumps((
            tuple(dataclasses.asdict(series) for series in request.series),
            request.y_axis_label,
            settings,
            locale.setlocale(locale.LC_TIME),
            (
                os.environ.get("TZ"),
                time.tzname,
                time.timezone,
                time.altzone,
                time.daylight,
            ),
        ))
    except ValueError:
        return None
    return hashlib.sha256(payload).hexdigest()


def cached_plot_content(key: str) -> bytes | None:
    """Reuse authenticated SVG bytes without interpreting executable cached objects.

    Args:
        key: The complete renderer input fingerprint.

    Returns:
        Exact SVG bytes, or None when the product is absent or malformed.
    """
    content = spatial_data.product_cache.get(PLOT_NAMESPACE, key)
    if content is None:
        return None
    try:
        root = defusedxml.ElementTree.fromstring(content)
    except defusedxml.ElementTree.ParseError, defusedxml.common.DefusedXmlException:
        return None
    return content if root.tag == "{http://www.w3.org/2000/svg}svg" else None


def plot_requests(
    fire_bundles: tuple[
        tuple[str, tuple[peri_scribe.kml.plot_data.FirePlot, ...]],
        ...,
    ],
) -> list[PlotRequest]:
    """Return one request per fire plot that survived the observation filter.

    Args:
        fire_bundles: Each fire's filename prefix and its plots, in fire order.

    Returns:
        The requests, in fire order and in each fire's plot order.
    """
    return [
        PlotRequest(
            fire_index=fire_index,
            filename_prefix=filename_prefix,
            filename_suffix=plot.filename_suffix,
            y_axis_label=plot.y_axis_label,
            series=series,
        )
        for fire_index, (filename_prefix, plots) in enumerate(fire_bundles)
        for plot in plots
        if (series := peri_scribe.kml.plot_data.retained_series(plot.series))
    ]


def plot_image_bundles(
    fire_bundles: tuple[
        tuple[str, tuple[peri_scribe.kml.plot_data.FirePlot, ...]],
        ...,
    ],
    *,
    before_rendering: typing.Callable[[], None] | None = None,
) -> tuple[tuple[PlotImage, ...], ...]:
    """Render every fire's plots.

    A fire's plot is skipped when none of its lines span enough observation times. When
    *before_rendering* is given the caller's work runs before the plots are drawn, so a
    caller can prepare data the folders will need.

    Args:
        fire_bundles: Each fire's filename prefix and its plots, in fire order.
        before_rendering: Work for the caller to run before rendering, or None.

    Returns:
        Each fire's rendered images, in the input fire order and in each fire's plot
        order.
    """
    requests = plot_requests(fire_bundles)
    images_by_fire: list[list[PlotImage]] = [[] for _fire in fire_bundles]
    if not requests:
        return tuple(tuple(images) for images in images_by_fire)
    if before_rendering is not None:
        before_rendering()
    for request, image in zip(
        requests,
        (render_plot_request(request) for request in requests),
        strict=True,
    ):
        images_by_fire[request.fire_index].append(image)
    return tuple(tuple(images) for images in images_by_fire)


def plot_filename(filename_prefix: str, filename_suffix: str) -> str:
    """Return the image filename for *filename_suffix* under *filename_prefix*.

    Args:
        filename_prefix: The fire's unique filename prefix.
        filename_suffix: The plot's suffix, like ``area``.

    Returns:
        The filename, like ``2026-cabug-000001-area.svg``.
    """
    image_format = svg_charts.time_series.IMAGE_FORMAT
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

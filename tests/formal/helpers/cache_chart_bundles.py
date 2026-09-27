"""Verify cached chart bytes remain attached to their current fire and plot slot."""

import dataclasses
import itertools
import pathlib

import pytest

import peri_scribe.execution
import peri_scribe.kml.plot_data
import peri_scribe.kml.plot_rendering
import spatial_data.product_cache
import svg_charts.time_series
import tests.formal.helpers.cache_dependencies
import tests.formal.helpers.oracle
import tests.helpers.factories.peri_scribe.kml.plot_rendering


CHART_COUNT = 3


def plots(owner: int) -> tuple[peri_scribe.kml.plot_data.FirePlot, ...]:
    """Distinguish both ownership and plot order, retaining one empty fire bundle.

    Args:
        owner: The stable input fire identity, independent of its current position.

    Returns:
        Zero, one, or two plots with unique visible series labels.
    """
    request = tests.helpers.factories.peri_scribe.kml.plot_rendering.plot_request()
    return tuple(
        peri_scribe.kml.plot_data.FirePlot(
            filename_suffix=f"plot-{index}",
            y_axis_label=request.y_axis_label,
            series=(
                dataclasses.replace(
                    request.series[0],
                    label=f"Owner {owner} plot {index}",
                ),
            ),
        )
        for index in range(owner)
    )


def expected_images(owner: int) -> tuple[peri_scribe.kml.plot_rendering.PlotImage, ...]:
    """Render independent uncached expectations from the owning input's plots.

    Args:
        owner: Stable fire identity whose complete current images are expected.

    Returns:
        Exact filenames and SVG bytes, preserving the owner's plot sequence.
    """
    return tuple(
        peri_scribe.kml.plot_rendering.PlotImage(
            filename=f"owner-{owner}-{plot.filename_suffix}.svg",
            content=svg_charts.time_series.draw_plot(
                plot.series,
                y_axis_label=plot.y_axis_label,
            ),
        )
        for plot in plots(owner)
    )


def compare(directory: pathlib.Path) -> None:
    """Require real cache hits and exact current ownership for every bundle ordering.

    Args:
        directory: Isolated persistent product storage.
    """
    contract = tests.formal.helpers.cache_dependencies.CHART
    ((complete, same_key, same_dependencies),) = tests.formal.helpers.oracle.evaluate(
        [contract.command("bundle")],
        executable="oracleCache",
    )
    assert complete == same_key == same_dependencies == 1
    owners = (0, 1, 2)
    expected = {owner: expected_images(owner) for owner in owners}
    contents = {image.content for images in expected.values() for image in images}
    assert len(contents) == CHART_COUNT
    path = directory / "products.sqlite"
    with pytest.MonkeyPatch.context() as monkeypatch:
        accesses = tests.formal.helpers.cache_dependencies.record_reads(
            monkeypatch,
            contract.namespace,
        )
        baseline = tuple((f"owner-{owner}", plots(owner)) for owner in owners)
        with (
            peri_scribe.execution.sharing(),
            spatial_data.product_cache.scope(path, "runtime"),
        ):
            actual = peri_scribe.kml.plot_rendering.plot_image_bundles(baseline)
        assert actual == tuple(expected[owner] for owner in owners)
        assert len(accesses) == CHART_COUNT
        assert all(not access.hit for access in accesses)
        keys = {
            0: (),
            1: (accesses[0].key,),
            2: (accesses[1].key, accesses[2].key),
        }
        assert len({key for owner_keys in keys.values() for key in owner_keys}) == (
            CHART_COUNT
        )
        for order in itertools.permutations(owners):
            inputs = tuple((f"owner-{owner}", plots(owner)) for owner in order)
            accesses.clear()
            with (
                peri_scribe.execution.sharing(),
                spatial_data.product_cache.scope(path, "runtime"),
            ):
                warm = peri_scribe.kml.plot_rendering.plot_image_bundles(inputs)
            assert len(accesses) == CHART_COUNT
            assert all(access.hit == bool(same_key) for access in accesses)
            assert all(access.context == "runtime" for access in accesses)
            assert tuple(access.key for access in accesses) == tuple(
                key for owner in order for key in keys[owner]
            )
            assert warm == tuple(expected[owner] for owner in order)
            with peri_scribe.execution.sharing():
                fresh = peri_scribe.kml.plot_rendering.plot_image_bundles(inputs)
            assert warm == fresh

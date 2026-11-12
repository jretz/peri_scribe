"""Reuse identical rendered previews in tests of update histories."""

import pathlib

import pytest

import peri_scribe.presentation.fire_data
import peri_scribe.presentation.preview_geometry
import peri_scribe.previews
import spatial_data.product_cache
import tests.helpers.factories.peri_scribe.presentation.preview_grid


@pytest.fixture(scope="session")
def update_preview_database(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Give each pytest worker a fresh, private cache of encoded preview images.

    Args:
        tmp_path_factory: Allocates private temporary directories for this worker.

    Returns:
        The location reserved for the worker's disposable preview database.
    """
    return tmp_path_factory.mktemp("update-previews") / "products.sqlite"


@pytest.fixture(scope="session")
def update_preview_grid() -> (
    tests.helpers.factories.peri_scribe.presentation.preview_grid.SharedGrid | None
):
    """Bind immutable preview inputs to this invocation's renderer and live owner.

    Returns:
        A qualified shared table, or None when the native renderer must build it.
    """
    return tests.helpers.factories.peri_scribe.presentation.preview_grid.current_grid()


@pytest.fixture
def reuse_update_previews(
    monkeypatch: pytest.MonkeyPatch,
    update_preview_database: pathlib.Path,
    update_preview_grid: (
        tests.helpers.factories.peri_scribe.presentation.preview_grid.SharedGrid | None
    ),
) -> None:
    """Cache real render outputs while keeping each test's history files separate.

    Args:
        monkeypatch: Restores ordinary preview rendering after the current test.
        update_preview_database: Private cache of the current worker's exact renders.
        update_preview_grid: Qualified immutable dart inputs shared by this invocation.
    """
    if update_preview_grid is not None:
        monkeypatch.setattr(
            peri_scribe.presentation.preview_geometry,
            "coarse_dart_hulls",
            update_preview_grid.get,
        )
    render = peri_scribe.previews.fire_preview

    def preview(fire: peri_scribe.presentation.fire_data.FireSummary) -> str | None:
        """Reuse production's key for the complete ordered geometry and colors.

        Args:
            fire: The fire and mapped observation selected by the test's real workflow.

        Returns:
            The actual lossless image for that observation, if it has drawable geometry.
        """
        with spatial_data.product_cache.scope(update_preview_database, "update-tests"):
            return render(fire)

    monkeypatch.setattr(peri_scribe.previews, "fire_preview", preview)

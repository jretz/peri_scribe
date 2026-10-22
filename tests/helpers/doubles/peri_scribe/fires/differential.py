"""Replace differential dependencies with controlled test doubles."""

import dataclasses
import pathlib
import typing

import peri_scribe.execution
import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import geopandas
    import shapely.geometry


@dataclasses.dataclass(frozen=True, kw_only=True)
class PublishedPerimeterReader:
    """Refuse duplicated point reads or source objects retained into growth work."""

    dataframe: geopandas.GeoDataFrame
    calls: list[str] = dataclasses.field(default_factory=list)

    def read(self, path: pathlib.Path, layer_name: str) -> geopandas.GeoDataFrame:
        """Expose only authenticated perimeters after source lifetime completion.

        Args:
            path: The full-history file selected by the production caller.
            layer_name: The requested published layer.

        Returns:
            The controlled full perimeter frame.

        """
        assert path.name == "history_of_full_geography.gpkg"
        assert layer_name == "perimeter_history"
        assert (
            peri_scribe.execution.get(peri_scribe.execution.Group.SOURCES, "lifetime")
            is None
        )
        self.calls.append(layer_name)
        return self.dataframe


def make_collapsing_difference(
    *,
    real_difference: typing.Callable[..., shapely.geometry.base.BaseGeometry | None],
) -> typing.Callable[..., shapely.geometry.base.BaseGeometry | None]:
    """Return a difference callback that simulates a collapsed growth sliver.

    Args:
        real_difference: Original geometry-difference operation used outside the
            collapsed case.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def collapsing_difference(
        current: shapely.geometry.base.BaseGeometry | None,
        previous: shapely.geometry.base.BaseGeometry | None,
    ) -> shapely.geometry.base.BaseGeometry | None:
        # A numerically degenerate sliver makes the covers-based growth check report
        # growth whose constructed difference collapses to nothing.
        """Simulate growth whose constructed difference collapses to no geometry.

        Args:
            current: Current mapped footprint used for growth measurement.
            previous: Previous mapped footprint, or None for the first observation.

        Returns:
            None for the selected degenerate case, otherwise the real difference.
        """
        if previous is not None and previous.equals(
            tests.helpers.factories.geometry.square(1.0),
        ):
            return None
        return real_difference(current, previous)

    return collapsing_difference

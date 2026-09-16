"""Replace differential dependencies with controlled test doubles."""

import typing

import tests.helpers.factories.geometry


if typing.TYPE_CHECKING:
    import shapely.geometry


def make_collapsing_difference(
    *,
    real_difference: typing.Callable[..., shapely.geometry.base.BaseGeometry | None],
) -> typing.Callable[..., shapely.geometry.base.BaseGeometry | None]:
    """Create a callback with controlled dependencies.

    Simulate growth whose constructed difference collapses to no geometry.

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

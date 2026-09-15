"""Provide data builders and stand-ins for files tests."""

from __future__ import annotations

import pathlib
import typing

import geopandas.testing

import peri_scribe.fires.derived_layers
import peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import peri_scribe.models


def assert_histories_equal(
    left: peri_scribe.fires.derived_layers.DerivedLayers,
    right: peri_scribe.fires.derived_layers.DerivedLayers,
) -> None:
    """Require reused and rebuilt histories to retain the same evidence and geometry.

    Args:
        left: The histories produced by an incremental rebuild.
        right: The independently rebuilt reference histories.
    """
    for name in ("perimeters", "points", "differential_perimeters", "incidents"):
        first = getattr(left, name)
        second = getattr(right, name)
        geopandas.testing.assert_geodataframe_equal(first, second)
        assert list(first.geometry.to_wkb()) == list(second.geometry.to_wkb())


def reject_history_reconstruction(*_args: object, **_kwargs: object) -> typing.Never:
    """Reject source reconstruction when a complete cached history is available.

    Args:
        _args: Unused derivation inputs.
        _kwargs: Unused derivation options.

    Raises:
        AssertionError: When an unchanged fire's evidence is reconstructed.
    """
    message = "An unchanged fire was recomputed"
    raise AssertionError(message)


def make_history_recorder(
    *,
    calls: list[str],
    derive: typing.Callable[
        ...,
        tuple[list[dict[str, object]], list[dict[str, object]]],
    ],
) -> typing.Callable[..., tuple[list[dict[str, object]], list[dict[str, object]]]]:
    """Create a callback with controlled dependencies.

    Observe which fires need reconstruction while preserving real derivation.

    Args:
        calls: Shared list recording dependency calls for assertions.
        derive: Original history derivation used to preserve real output behavior.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def tracked(
        fire: peri_scribe.models.Fire,
        group: tuple[int, ...],
        full_rows: list[peri_scribe.geo.package.FireRowRecord],
        full_paths: list[pathlib.Path],
        *,
        sources_directory: pathlib.Path,
        classification: peri_scribe.models.FireClassification | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Observe which fires need reconstruction while preserving real derivation.

        Args:
            fire: The fire being reconstructed.
            group: Its source-record positions.
            full_rows: The source observations for this test.
            full_paths: The corresponding snapshot paths.
            sources_directory: The base for snapshot provenance.
            classification: The selected border classification.

        Returns:
            The derived perimeter and point rows.
        """
        calls.append(fire.name)
        return derive(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classification,
        )

    return tracked

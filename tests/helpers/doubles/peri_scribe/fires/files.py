"""Replace files dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import peri_scribe.models


def reject_history_reconstruction(*args: object, **kwargs: object) -> typing.Never:
    """Reject source reconstruction when a complete cached history is available.

    Args:
        args: Unused derivation inputs.
        kwargs: Unused derivation options.

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

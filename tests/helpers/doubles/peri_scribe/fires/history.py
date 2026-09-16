"""Replace history dependencies with controlled test doubles."""

from __future__ import annotations

import pathlib
import typing

import peri_scribe.geo.package


if typing.TYPE_CHECKING:
    import peri_scribe.models


def make_failing_history_reader(
    *,
    real_history_rows_for_fire: typing.Callable[
        ...,
        tuple[list[dict[str, object]], list[dict[str, object]]],
    ],
) -> typing.Callable[..., tuple[list[dict[str, object]], list[dict[str, object]]]]:
    """Create a callback with controlled dependencies.

    Fail one fire's history computation to exercise worker error propagation.

    Args:
        real_history_rows_for_fire: Original history reader used for nonfailing fires.

    Returns:
        The callback bound to the supplied dependencies.
    """

    def failing_history_rows_for_fire(
        fire: peri_scribe.models.Fire,
        group: tuple[int, ...],
        full_rows: list[peri_scribe.geo.package.FireRowRecord],
        full_paths: list[pathlib.Path],
        *,
        sources_directory: pathlib.Path,
        classification: peri_scribe.models.FireClassification | None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Fail one fire's history computation to exercise worker error propagation.

        Args:
            fire: Fire whose observations are being grouped or derived.
            group: Indices selecting this fire's rows from the complete input.
            full_rows: All source rows available to the history computation.
            full_paths: Source paths aligned with the complete row collection.
            sources_directory: Root directory used to resolve source provenance.
            classification: Optional border classification attached to the derived
                history.

        Returns:
            The real perimeter and point rows for fires outside the failing case.

        Raises:
            RuntimeError: If the selected fire is the configured failure case.
        """
        if fire.identifier == "2026-cacdd-000003":
            message = "perimeter failure"
            raise RuntimeError(message)
        return real_history_rows_for_fire(
            fire,
            group,
            full_rows,
            full_paths,
            sources_directory=sources_directory,
            classification=classification,
        )

    return failing_history_rows_for_fire

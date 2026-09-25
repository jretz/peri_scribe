"""Shared perimeter policy for geography generation and historical replay."""

import peri_scribe.models
import peri_scribe.perimeters.size_filtering
import peri_scribe.perimeters.versions


def reconcile(
    observations: list[peri_scribe.perimeters.versions.SourceObservation],
    classification: peri_scribe.models.FireClassification | None,
) -> list[peri_scribe.perimeters.versions.SourceObservation]:
    """Apply source preference, version collapse, and minimum-size validation.

    Args:
        observations: All source records available for one fire.
        classification: The fire's geographic source preference.

    Returns:
        The perimeter history eligible for geometry cleaning and publication.
    """
    firis = [
        observation
        for observation in observations
        if observation.source_kind is peri_scribe.perimeters.versions.FIRIS_PERIMETER
    ]
    wfigs = [
        observation
        for observation in observations
        if observation.source_kind is peri_scribe.perimeters.versions.WFIGS_PERIMETER
    ]
    return peri_scribe.perimeters.size_filtering.drop_implausibly_small_perimeters(
        peri_scribe.perimeters.versions.reconcile_perimeter_versions(
            peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
                firis,
            ),
            peri_scribe.perimeters.versions.collapse_identical_consecutive_perimeters(
                wfigs,
            ),
            classification,
        ),
    )

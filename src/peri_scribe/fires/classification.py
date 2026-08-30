"""Classifying fires relative to the California interstate border."""

from __future__ import annotations

import concurrent.futures
import functools
import os
import pathlib

import structlog

import peri_scribe.fires.sources
import peri_scribe.models
import peri_scribe.perimeters.border_classification


logger = structlog.get_logger()


def classify_fire_group(
    group: tuple[int, ...],
    record_groups: peri_scribe.fires.sources.FireRecordGroups,
    boundaries: peri_scribe.perimeters.border_classification.Boundaries,
) -> peri_scribe.models.FireClassification:
    """Classify the fire identified by *group* in *record_groups*.

    Args:
        group: The record indices of one fire.
        record_groups: The grouped fire records.
        boundaries: The California polygon and border in California Albers.

    Returns:
        The fire's border classification and evidence.
    """
    return peri_scribe.perimeters.border_classification.classify_fire(
        records=[record_groups.records[index] for index in group],
        record_paths=[record_groups.record_paths[index] for index in group],
        boundaries=boundaries,
    )


def classify_fire_sources(
    record_groups: peri_scribe.fires.sources.FireRecordGroups,
    year_directory: pathlib.Path,
) -> dict[int, peri_scribe.models.FireClassification]:
    """Classify each non-complex fire relative to the California boundary.

    Each fire's classification is independent, and the geometry work in
    California Albers releases the GIL, so the fires are classified in parallel
    and the results are collected in group order.

    Args:
        record_groups: The grouped fire records.
        year_directory: The year directory that holds the administrative boundary data.

    Returns:
        Each non-complex fire's classification, keyed by the fire object's identity.
    """
    pairs = peri_scribe.fires.sources.non_complex_fire_sources(record_groups)
    if not pairs:
        return {}
    try:
        boundaries = peri_scribe.perimeters.border_classification.load_boundaries(
            year_directory,
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning("Skipping border classification", error=str(error))
        return {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=os.cpu_count() or 1,
    ) as executor:
        return {
            id(source.fire): classification
            for (source, _group), classification in zip(
                pairs,
                executor.map(
                    functools.partial(
                        classify_fire_group,
                        record_groups=record_groups,
                        boundaries=boundaries,
                    ),
                    [group for _source, group in pairs],
                ),
                strict=True,
            )
        }

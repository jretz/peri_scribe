"""Indexed and streamed evacuation queries agree with proved closed intersections."""

import pathlib

import spatial_data.overlaps
import tests.formal.helpers.oracle
import tests.formal.helpers.spatial_overlap


def test_overlapping_layer_indices_matches_exact_model_with_sparse_geopackages(
    tmp_path: pathlib.Path,
) -> None:
    queries = tests.formal.helpers.spatial_overlap.queries()
    cases = tests.formal.helpers.spatial_overlap.feature_sets()
    commands = [
        "overlap "
        + tests.formal.helpers.spatial_overlap.transport(queries)
        + " "
        + tests.formal.helpers.spatial_overlap.transport(features)
        for features in cases
    ]
    expected = tests.formal.helpers.oracle.evaluate(
        commands,
        executable="oracleSpatial",
    )
    geometries = [
        None if index == 0 else tests.formal.helpers.spatial_overlap.geometry(shape)
        for index, shape in enumerate(queries)
    ]
    for case, (features, result) in enumerate(zip(cases, expected, strict=True)):
        for indexed in (False, True):
            for projected in (False, True):
                path = tmp_path / f"zones-{case}-{indexed}-{projected}.gpkg"
                tests.formal.helpers.spatial_overlap.write_layer(
                    path,
                    features,
                    indexed=indexed,
                    projected=projected,
                )
                assert spatial_data.overlaps.has_rtree(path, "zones") == indexed
                for chunk_size in (1, 3, 100):
                    actual = spatial_data.overlaps.overlapping_layer_indices(
                        geometries,
                        path,
                        "zones",
                        chunk_size,
                    )
                    assert actual == set(result), (case, indexed, projected, chunk_size)

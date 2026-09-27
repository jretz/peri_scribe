"""Real sparse GeoPackages exercise both spatial indexes and streamed fallbacks."""

import itertools
import pathlib

import geopandas
import numpy as np
import shapely


Box = tuple[int, int, int, int]
Shape = tuple[Box, ...]


def geometry(shape: Shape) -> shapely.Geometry:
    """Closed rectangles retain point and edge contacts in the actual GEOS fixtures.

    Args:
        shape: A finite union, possibly empty or containing degenerate rectangles.

    Returns:
        The exact closed union represented in longitude and latitude coordinates.
    """
    parts = []
    for left, bottom, right, top in shape:
        if left == right and bottom == top:
            parts.append(shapely.Point(left, bottom))
        elif left == right or bottom == top:
            parts.append(shapely.LineString([(left, bottom), (right, top)]))
        else:
            parts.append(shapely.box(left, bottom, right, top))
    return shapely.union_all(parts)


def transport(shapes: list[Shape]) -> str:
    """Preserve original positions even when a query has no footprint.

    Args:
        shapes: Closed unions for one side of the query.

    Returns:
        The oracle's rectangle-list representation.
    """
    return (
        ";".join(
            ":".join(",".join(map(str, box)) for box in shape) or "n"
            for shape in shapes
        )
        or "empty"
    )


def queries() -> list[Shape]:
    """Envelope false positives, holes, touches, and duplicate queries need exact tests.

    Returns:
        A shared query population with empty positions and duplicate identities.
    """
    values: list[Shape] = [(), (), ((0, 0, 1, 1),), ((0, 0, 1, 1),)]
    values.extend(
        ((left, bottom, left + width, bottom + height),)
        for left, bottom, (width, height) in itertools.product(
            range(-1, 5),
            range(-1, 5),
            ((0, 0), (0, 1), (1, 0), (1, 1), (2, 2)),
        )
    )
    values.extend([
        ((0, 0, 1, 4), (3, 0, 4, 4), (1, 0, 3, 1), (1, 3, 3, 4)),
        ((-1, -1, 0, 0), (4, 4, 5, 5)),
    ])
    return values


def feature_sets() -> list[list[Shape]]:
    """Repeated and sparse features expose identity mistakes hidden by dense layers.

    Returns:
        Fixed and reproducibly generated valid rectangle unions.
    """
    values = queries()
    cases: list[list[Shape]] = [
        [(), ()],
        [((0, 0, 1, 1),)],
        [values[-2]],
        [values[-1]],
        [(), ((0, 0, 1, 1),), (), ((0, 0, 1, 1),)],
        [((0, 0, 0, 0),), ((1, 0, 1, 2),), ((2, 1, 4, 1),)],
    ]
    generator = np.random.default_rng(20261001)
    cases.extend(
        [values[int(index)] for index in generator.integers(0, len(values), 9)]
        for _ in range(10)
    )
    return cases


def write_layer(
    path: pathlib.Path,
    shapes: list[Shape],
    *,
    indexed: bool,
    projected: bool,
) -> None:
    """GDAL writes the real feature IDs, blobs, metadata, and optional R-tree.

    Args:
        path: Isolated GeoPackage destination.
        shapes: Complete source features, including null and empty footprints.
        indexed: Whether the file should contain a spatial index.
        projected: Whether features should be stored in Web Mercator.
    """
    frame = geopandas.GeoDataFrame(
        {
            "fid": [1 + index * index * 997 for index in range(len(shapes))],
            "geometry": [
                None if not shape and index % 2 == 0 else geometry(shape)
                for index, shape in enumerate(shapes)
            ],
        },
        crs="EPSG:4326",
    )
    if projected:
        frame = frame.to_crs("EPSG:3857")
    frame.to_file(
        path,
        layer="zones",
        geometry_type="Unknown",
        layer_options={"SPATIAL_INDEX": "YES" if indexed else "NO"},
    )

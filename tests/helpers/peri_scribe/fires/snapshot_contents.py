"""Edit real point snapshots while preserving the obsolete freshness signals."""

import contextlib
import os
import pathlib
import sqlite3


def rename_point_snapshot(
    path: pathlib.Path,
    layer: str,
    name: str,
) -> tuple[os.stat_result, os.stat_result]:
    """Rename the fixture's fire without changing its file or bucket modification time.

    The caller creates the snapshot with the point-cache factory, whose geometries are
    nonempty points at (0, 0). The registered SQLite functions preserve those RTree
    bounds while an attribute-only update runs the GeoPackage's normal triggers.

    Args:
        path: The real point snapshot to edit in place.
        layer: Its configured feed layer.
        name: The replacement fire name, normally equal in length to the original.

    Returns:
        The original file and bucket-directory metadata for regression assertions.
    """
    source_stamp = path.stat()
    bucket_stamp = path.parent.stat()
    with contextlib.closing(sqlite3.connect(path)) as connection, connection:
        connection.create_function("ST_IsEmpty", 1, lambda _blob: False)
        for function in ("ST_MinX", "ST_MinY", "ST_MaxX", "ST_MaxY"):
            connection.create_function(function, 1, lambda _blob: 0)
        connection.execute(f'UPDATE "{layer}" SET incident_name = ?', (name,))
    os.utime(path, ns=(source_stamp.st_atime_ns, source_stamp.st_mtime_ns))
    os.utime(path.parent, ns=(bucket_stamp.st_atime_ns, bucket_stamp.st_mtime_ns))
    return source_stamp, bucket_stamp

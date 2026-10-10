# Compact point storage and batched containment

## Contract and assessment

The database represents a **bag** of finite, valid WGS84 points: repeated coordinates
remain separate records. Longitude and latitude become signed little-endian int32 pairs
at `10^-5` degree resolution. Queries return one count per input geometry, using strict
containment of decoded stored points; points on polygon boundaries are excluded. Missing
or empty query geometry, or an absent database, yields zero for that slot.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 1 | Construction accumulates partitions before emitting complete tiles. |
| Rule interaction | 2 | Quantization, endpoint tile clamping, inclusive envelope filtering, and strict containment must agree. |
| Mathematical reasoning | 2 | Signed rounding and conservative encoded envelopes must retain every possible stored-point match. |
| Scale and representation | 3 | Partitioned fixed-width records and compressed tiles define both reconstruction and resource use. |
| Failure and concurrency | 3 | Archive workers must exit before temporary files disappear; validation precedes final replacement. |

**Complex: 11.** The counts influence published fire scoring, so duplicate handling and
the distinction between raw and quantized coordinates are part of the policy contract.

## Construction and publication

[Centroid conversion](building-centroids.md) supplies chunks. Each point is rounded to
nearest integer with even ties. Tile columns and rows span 0.5 degrees from `(-180,-90)`;
the easternmost column and northernmost row also include the upper world endpoints.
For encoded `(x,y)`, the tile is `720 × row + column`, and the temporary partition is
`tile mod 16`. All records of one tile necessarily land in the same partition.

![Chunks become whole-tile compressed records through modulo partitions](assets/point-partitions.svg)

The same tile from separate archive chunks reaches one partition. Sorting records
cannot deduplicate them; the example retains both copies of point A.

Construction reads one whole partition into NumPy, sorts by tile ID, and writes one
SQLite row per occupied tile. Within a tile, raw eight-byte records are sorted for
compression and compressed with zstd. Spatial record order has no semantic meaning.
Metadata fixes CRS, axis order, scale, byte order, record size, tile size, and format
version. Validation compares that metadata and the tiles schema; it does **not** scan
and authenticate every compressed payload.

The buildings owner allows three concurrent archive converters. Appends share a lock.
Cancellation sets a cooperative stop signal and waits for worker exit while retaining
the semaphore and temporary directory. After workers finish, construction closes the
SQLite database, validates the staged format, and atomically replaces the final path.
Failure before replacement preserves the prior final file; cancellation cannot safely
force a stuck blocking thread to exit. This assumes same-filesystem replacement and
cooperating ownership, and makes no power-loss durability claim.

## Query argument and example

![Tile selection, encoded envelope filtering, and exact containment](assets/point-query.svg)

Each stage narrows candidates while retaining all possible matches in stored coordinates.
Two copies of an interior point count twice; an envelope false positive and a boundary
point count zero. Static stages show the complete argument without animation.

The query groups polygons by tile, reads and decompresses each requested tile once,
then handles each polygon's candidates separately. An inclusive integer envelope filter
precedes `contains_xy` on decoded degrees. Because rounding is monotone and fixes integer
ticks, a stored integer point inside the real query envelope survives rounded bounds.
The broad filter may retain extra points; only strict geometry containment decides the
count. Prepared geometry is destroyed after each containment call.

For example, two records at `(-122.50000,37.75000)` inside a polygon contribute two.
A third record exactly on its exterior contributes zero. A raw point at longitude
`-122.500004` rounds to `-122.50000`; membership can change if a boundary falls between
those coordinates. The contract concerns the stored bag, so precision loss is explicit.
Using the tile's total count as a polygon count would be incorrect near holes or edges.

## Costs, alternatives, and verification

Let `N` be points, `M` the largest partition population, `T` the largest requested tile,
`Q` query geometries, and `E` query/tile associations. Ingestion is O(N); partition
sorting costs the sum of per-partition sorting work, conventionally O(N log N) overall.
Peak build arrays scale with M, including permutation/index arrays and a tile's compressed
payload. Sixteen partitions reduce typical memory; they do not bound skew or tile density.

Queries retain O(E + Q) routing metadata plus O(T) point/candidate arrays and the query
geometries. Every polygon assigned a tile scans that tile's points for its envelope;
polygon predicate cost depends on geometry complexity. A database R-tree per point could
avoid some scans but carries much more per-record storage. Fixed tiles favor compressed
national datasets and repeated nearby queries.

Implementation: [point_store.py](../../src/spatial_data/point_store.py) and
[buildings.py](../../src/peri_scribe/sources/buildings.py).
Ordinary [point-store tests](../../tests/tests/standard/spatial_data/test_point_store.py)
and [generated cases](../../tests/tests/property_based/spatial_data/test_point_store.py)
exercise encoding, tiles, multiplicity, and queries. Formal connections include
[PointConstruction](../../tests/formal/lean/PeriScribe/PointConstruction.lean),
[CoordinateQuantization](../../tests/formal/lean/spatial_boundaries.md),
[BuildingsConstruction and WorkerLifetime](../../tests/formal/tla/ingestion.md), and
conformance for [partition bags](../../tests/formal/conformance/test_point_construction.py),
[quantization](../../tests/formal/conformance/test_coordinate_quantization.py), and
[construction lifecycle](../../tests/formal/conformance/test_buildings_construction.py).
These prove ideal partition/rounding properties and explore bounded lifecycle cases;
NumPy, binary64 multiplication, SQLite, GEOS, and external dataset truth remain boundaries.

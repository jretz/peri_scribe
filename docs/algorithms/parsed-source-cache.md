# Authenticated parsed source cache

Parsed source rows can be reused only when they belong to the current snapshot bytes.
The receipt, rows, and complex memberships must also belong to one database generation.
Otherwise a cache hit could silently mix identities from different observations.

## Contract and assessment

Inputs are authoritative snapshot GeoPackages and a disposable per-feed SQLite database.
Outputs are source-ordered records and memberships equivalent to parsing the snapshot.
Cache absence, schema mismatch, failed authentication, and caught storage or decoding
errors cause direct parsing or rebuilding. Source snapshots remain authoritative;
fallback does not cover every possible payload corruption.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Cache synchronization follows a changing snapshot inventory. |
| Rule interaction | 2 | Metadata shortcuts, checksums, schema versions, and fallback interact. |
| Mathematical reasoning | 1 | Checksums and keyed comparison use established operations. |
| Scale and representation | 2 | Serialized records avoid repeated geospatial parsing. |
| Failure and concurrency | 3 | Readers authenticate and consume one transaction despite concurrent rewrites. |

Total **10: complex**.

## Synchronize and read

Replacing a snapshot's cached rows and its checksum receipt in one transaction prevents
an authenticated receipt from naming incomplete contents.

Synchronization proceeds in this order:

1. Compare the stored serial, size, modification time, and SHA-256 digest with the
   current authoritative snapshot inventory.
2. Remove rows and memberships for missing snapshots. For changed snapshots, remove
   superseded contents and insert newly parsed rows and complex memberships.
3. Write the matching checksum receipts and commit the transaction, making receipts
   and their complete contents visible together.

A schema mismatch rebuilds the database. Directory metadata can avoid repeating
synchronization, but cannot authorize an individual cached read by itself.

Each lookup authenticates and consumes one database generation:

1. Hash the actual snapshot file, so preserved timestamps cannot disguise changed bytes.
2. Open a savepoint and require a receipt matching the requested serial and current
   checksum. The savepoint preserves one read transaction even when the caller already
   owns an outer transaction.
3. Read rows and memberships before releasing that same savepoint. Preserve row
   insertion order through `rowid` ordering.
4. Return the cached parse. An absent receipt yields no cache result; lookup errors of
   type `OSError`, `ValueError`, or `sqlite3.Error` also fall back to the authoritative
   GeoPackage.

## Example and correctness argument

Suppose snapshot 12 is replaced with corrected coordinates while its byte length and
modification time are preserved. A metadata-only cache accepts stale rows; this cache's
per-read byte checksum rejects them. Now suppose a writer replaces the cache after the
reader checks the receipt. Reading each table in separate transactions could combine
old rows with new memberships. The shared read transaction observes one generation.

The key invariant is that a returned cached parse has a matching authoritative checksum
and internally consistent receipt/rows/memberships under the cooperating-writer
contract. Detected failures remove an acceleration opportunity. This checksum identifies
the source snapshot; it does not independently authenticate every cached row payload.
Malformed cached WKB can raise a Shapely `GEOSException` outside the caught error set.
Source I/O errors also remain possible: direct parsing can fail when authoritative data
is unavailable. The formal cache protocol does not establish arbitrary-corruption recovery.

## Costs, limitations, and verification

Reading a snapshot of `B` bytes still requires `O(B)` hashing. A hit avoids geometry and
attribute parsing, but loads its cached records and memberships. Synchronization hashes
the discovered files and parses changed ones. The database, filesystem, and cooperating
source-writer assumptions are explicit boundaries; hash equality assumes collision
resistance. This is not an adversarial authentication scheme or a cross-file transaction.

- [Database synchronization](../../src/peri_scribe/geo/database.py),
  [transactional reads](../../src/peri_scribe/geo/reading.py), and
  [record codec](../../src/peri_scribe/geo/package.py).
- [ParsedCache](../../tests/formal/tla/ParsedCache.tla),
  [ParsedCacheRead](../../tests/formal/tla/ParsedCacheRead.tla), and
  [ParsedCacheRebuild](../../tests/formal/tla/ParsedCacheRebuild.tla).
- [Conformance](../../tests/formal/conformance/test_parsed_cache.py) checks the concrete
  transaction/fallback behavior; the [model inventory](../../tests/formal/tla/README.md)
  states the finite model domains.

Prepared application facts use [product caching](product-caching.md), a different cache
whose keys include derivation and runtime dependencies.

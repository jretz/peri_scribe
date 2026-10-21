# Parsed snapshot cache

`record_cache.db` stores parsed source snapshots separately from the prepared product
cache. Every fire row and complex membership returned from it must belong to the
snapshot authenticated by the checksum receipt. Checking the receipt and then reading
rows from a different generation would defeat that check. Missing or stale entries and
caught read errors fall back to the authoritative snapshot.

| Model | Production owner | Checked guarantee |
| --- | --- | --- |
| `ParsedCache` | `geo.database.write_snapshot`, `sync_database`, `open_and_sync` | Replacements, additions, and removals commit their receipts, rows, and memberships together. Interrupted statements and commits preserve the previous complete inventory. |
| `ParsedCacheRead` | `geo.reading.fetch_snapshot_rows`, `read_snapshot_contents` | A reader pins its checksum check and both payload queries to one SQLite transaction. Concurrent replacement or deletion cannot change authenticated contents or mix generations. |
| `ParsedCacheRebuild` | `geo.database.reset_database`, `ensure_database_current` | Interrupted schema replacement yields complete authenticated data or a cache miss. Restarting the reset and synchronizing produces the authoritative contents. |
| `NormalizedCache` | `geo.database.intern_payload`, `normalized_row`, `collect_unreferenced_payloads`, `geo.reading.fetch_snapshot_batch` | Exact dictionary reconstruction retains ordered repeated observations. Dictionary allocation, reclamation, receipt publication, and abort preserve every surviving reference. |
| `SourceSummaries` | `geo.source_summaries.read_summaries`, `read_snapshot_summary`, `seed_summaries` | Current authenticated path/content identities select exact ordered slim products; absent, damaged or incompatible products hydrate the current snapshot. |

`SourceSummaries` explores 768 states, including all 256 completed selections for two
snapshot paths, two current and saved revisions, and absent, damaged, old-context or
complete product modes. It checks ordered projection equality and hydration exactly
when a matching complete product is unavailable. The conformance test replays every
completed selection through actual product storage, source-byte authentication, parsed
snapshot hydration and projection construction. Durable product publication and storage
checksums retain the existing product-cache protocol; completed summary construction is
an explicit model assumption checked by codec, ownership and generated anchor-subset
regressions. The model abstracts SHA-256, filesystem stability, geometry, JSON and the
source-index coordinator's separate dependency-closure selection.

`ParsedCache` explores 234 states: two snapshot serials, three initial inventories, four
requested inventories, and every replacement or deletion statement boundary. Revision
zero denotes absence; revisions one and two denote distinct complete source parses. An
insertion action represents an entire parsed row or membership group. SQLite may fail
inside an insertion group; the group is incomplete until all its members are inserted,
and no uncommitted group is visible through a separate connection.

`ParsedCacheRead` explores 696 states containing 288 complete reader schedules. It
checks three committed cache states (missing, revision one, revision two), two requested
checksums, all four placements of a concurrent commit around the three SELECTs, and
failure of each SELECT. The writer can remove or replace the requested snapshot. WAL
conformance permits commits during the reader transaction; SQLite's default journal mode
also preserves the transaction and can block a competing commit until the reader ends.

`ParsedCacheRebuild` explores 92 states, including interruption and one restart before
or after any of the fifteen schema statements. Its reader uses the pinned read contract
from `ParsedCacheRead`; table removal produces a read error, and newly created tables
contain no receipt until synchronization succeeds. The old parse and the rebuilt parse
are each complete. These are safety models. Successful retry is checked as a reachable
outcome; no claim requires the application to keep retrying a disposable cache
indefinitely.

`NormalizedCache` explores 654 states across all 36 pairs of original and replacement
sequences. There are two distinct exact payload values and two dictionary keys. Empty,
single, repeated, and reversed observations exercise order and multiplicity. Allocation
can reuse only an exactly equal value; a digest index is deliberately outside equality.
Collection retains every key referenced by surviving pending rows. Publication replaces
dictionary, rows, and receipt together; abort restores the previous complete generation.
A read consumes receipt and decoded references from one durable generation. These
bounds check the representation protocol, not arbitrary dictionaries or SQLite internals.

## Connection to the implementation

`conformance/test_parsed_cache.py` consumes actual TLC exports. It compares every reader
schedule with two real SQLite connections and checks complete decoded payloads,
including geometry, timestamps, identifier and name sets, optional fields, nested
attributes, row ordering, and complex memberships. Read failures must produce a miss and
release the reader transaction.

For all twelve inventory changes, the bridge runs the production synchronization against
real SQLite tables and authenticated source bytes. It interrupts 176 concrete mutation
and commit boundaries, including partial `executemany` groups, closes the connection,
and compares the durable result with the model's aborted state. Healthy synchronization
must match the model's committed state. A continuous graph-path matcher now also follows
every real committed-table observation, explicit abort, restart, and healthy commit. The
bridge substitutes only GeoPackage parsing with distinct parsed fixtures; cache
serialization, source discovery, checksums, metadata, SQL, transaction cleanup, and
subsequent reads remain real. Dictionary inserts and reclamation are included in the
concrete interruption matrix. The logical observer reconstructs complete payload values
from dictionary references, so changing a reference or dropping a live payload changes
the observed contract rather than disappearing behind an integer ID.

For all thirty-two initial schema prefixes, it interrupts the actual DDL, checks the
model's read outcome, verifies authoritative fallback through `read_cached_snapshot`,
and runs `ensure_database_current` to repair the cache using the same continuous path
matcher. The [execution extension](../execution_paths_extensions.md) describes exact
row/schema projections and the two explicit retry-model additions. Ordinary GeoPackage
cache tests additionally exercise actual source parsing, outdated schemas, corrupt
databases, and failed rebuilds.

`conformance/test_normalized_cache.py` takes every checked published and aborted
original/target pair from `NormalizedCache`. It exercises actual row encoding,
dictionary allocation, transaction commit or rollback, reclamation, authenticated batch
reconstruction, and exact ordered row equality. It also requires the surviving payload
counts to match distinct retained encodings. Ordinary regressions force digest collisions,
missing references, changed dictionary content, nested attribute mutations, and preserved
SRID/coordinate dimensions. The publication/abort test supplements the statement-level
interruption bridge; it does not by itself prove every concrete operation refines a
particular TLA+ transition.

The models exposed a reader race: checking a checksum, then allowing a concurrent commit
before either payload SELECT, could return a replacement generation or even an empty
parse after deletion. `fetch_snapshot_rows` now owns a savepoint around all three
queries. Four ordinary regressions reproduced the failure before that change; another
confirms that borrowing an existing caller transaction does not commit the caller's
pending work.

## Assumptions and limits

Snapshot contents remain stable throughout each checksum and parse operation. Rewrites
between operations are covered; an external program replacing bytes during a parse is
outside this contract. The pipeline's cooperating writer lock and immutable published
snapshots supply this assumption for application writers. Checksum identity is treated
as collision-free, parsing is deterministic, and stored bytes have not been maliciously
edited independently of their receipts.

SQLite supplies transaction isolation and rollback. The checks exercise process and SQL
interruption, including failed commit; they do not establish storage-device behavior,
power-loss durability, or SQLite's implementation correctness. Two serials and two
nonempty payload generations are finite bounds, not a proof for arbitrary inventories.
The rebuild model assumes that a retained old parse remains valid for its recorded
checksum; schema-version changes still force a rebuild through the production entry
point. The modeled failed-read outcome covers missing tables and caught `OSError`,
`ValueError`, or `sqlite3.Error` failures. Other payload-decoding errors, such as malformed
WKB raising `GEOSException`, are outside the fallback guarantee.

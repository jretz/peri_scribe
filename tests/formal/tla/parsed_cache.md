# Parsed snapshot cache

`record_cache.db` stores parsed source snapshots. It is independent of the prepared
product cache. Its correctness condition is that a checksum receipt authenticates every
fire row and complex membership returned with that receipt. A failed or stale cache read
must fall back to the authoritative snapshot.

| Model | Production owner | Checked guarantee |
| --- | --- | --- |
| `ParsedCache` | `geo.database.write_snapshot`, `sync_database`, `open_and_sync` | Replacements, additions, and removals commit their receipts, rows, and memberships together. Interrupted statements and commits preserve the previous complete inventory. |
| `ParsedCacheRead` | `geo.reading.fetch_snapshot_rows`, `read_snapshot_contents` | A reader pins its checksum check and both payload queries to one SQLite transaction. Concurrent replacement or deletion cannot change authenticated contents or mix generations. |
| `ParsedCacheRebuild` | `geo.database.reset_database`, `ensure_database_current` | Interrupted schema replacement yields complete authenticated data or a cache miss. Restarting the reset and synchronizing produces the authoritative contents. |

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

`ParsedCacheRebuild` explores 64 states, including interruption and one restart before
or after any of the eight schema statements. Its reader uses the pinned read contract
from `ParsedCacheRead`; table removal produces a read error, and newly created tables
contain no receipt until synchronization succeeds. The old parse and the rebuilt parse
are each complete. These are safety models. Successful retry is checked as a reachable
outcome; no claim requires the application to keep retrying a disposable cache
indefinitely.

## Connection to the implementation

`conformance/test_parsed_cache.py` consumes actual TLC exports. It compares every reader
schedule with two real SQLite connections and checks complete decoded payloads,
including geometry, timestamps, identifier and name sets, optional fields, nested
attributes, row ordering, and complex memberships. Read failures must produce a miss and
release the reader transaction.

For all twelve inventory changes, the bridge runs the production synchronization against
real SQLite tables and authenticated source bytes. It interrupts 110 concrete mutation
and commit boundaries, including partial `executemany` groups, closes the connection,
and compares the durable result with the model's aborted state. Healthy synchronization
must match the model's committed state. A continuous graph-path matcher now also follows
every real committed-table observation, explicit abort, restart, and healthy commit. The
bridge substitutes only GeoPackage parsing with distinct parsed fixtures; cache
serialization, source discovery, checksums, metadata, SQL, transaction cleanup, and
subsequent reads remain real.

For all eighteen initial schema prefixes, it interrupts the actual DDL, checks the
model's read outcome, verifies authoritative fallback through `read_cached_snapshot`,
and runs `ensure_database_current` to repair the cache using the same continuous path
matcher. The [execution extension](../execution_paths_extensions.md) describes exact
row/schema projections and the two explicit retry-model additions. Ordinary GeoPackage
cache tests additionally exercise actual source parsing, outdated schemas, corrupt
databases, and failed rebuilds.

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
point. Invalid serialized values and missing tables use the modeled failed-read outcome.

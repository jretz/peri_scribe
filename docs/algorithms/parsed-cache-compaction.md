# Ordered parsed-cache compaction

Parsed snapshot caches can retain large unused regions after schema rebuilding or
payload reclamation. Compaction replaces only this disposable cache, keeping every
stored value and occurrence key unchanged. Authoritative source GeoPackages retain
their original format, organization and bytes.

## Contract and assessment

The input is one synchronized parsed-cache SQLite database. The output is either that
same usable database or a complete compact replacement with the same schema version,
receipts, ordered rows, memberships and dictionary payloads. In particular, repeated
observations remain separate and retain their implicit rowids. Those rowids determine
source occurrence order in existing readers.

| Dimension | Score | Reason |
| --- | ---: | --- |
| History and state | 2 | Receipts and ordered occurrences retain observations across snapshot replacement. |
| Rule interaction | 1 | Exact value and occurrence-key identity determine whether replacement is admissible. |
| Mathematical reasoning | 1 | A bijective copy of every keyed table preserves all references and ordering. |
| Scale and representation | 3 | Streaming reconstruction must retain relationships without loading the complete cache. |
| Failure and concurrency | 3 | Staging, validation, connection retirement and publication have separate failure boundaries. |

Total **10: complex**. The supported failure model is process termination with atomic
same-filesystem replacement. Power-loss durability and unrelated programs modifying
the cache without its writer lock are outside this contract.

## Ownership and replacement

Every production cache synchronizer acquires a stable neighboring `.lock` file before
opening its SQLite writer. Ownership spans recovery of a damaged database, source
synchronization, writer closure and optional compaction. The lock file survives database
replacement so another process cannot enter through a newly created inode. The
in-process record-cache lock continues to serialize local source preparation.

Compaction requires both at least eight MiB of unused pages and an unused fraction of
at least one quarter. These bounds amortize a complete live-data copy against meaningful
space savings. They do not promise a specific compaction duration. A database using
anything other than SQLite's normal `delete` journal mode is retained: a WAL database
has companion files whose lifetime needs a different replacement protocol.

Under the writer lock, the compactor removes abandoned staging directories belonging
to that cache's reserved filename prefix. The prefix contains the database filename,
so cleanup cannot retire another cache's active staging directory. Staging directories
contain only unpublished disposable files. A published database is outside them.

For an eligible database:

1. Open the original read-only and pin one read transaction. Create a private SQLite
   database beside it with the current tables and indexes.
2. Copy `snapshots`, `rows`, `memberships`, `geometry_payloads` and
   `attribute_payloads`. Each insertion explicitly supplies the original `rowid` and
   every column value. SQLite cursors stream the records in rowid order.
3. Copy the schema version and commit the candidate. Compare every candidate table with
   its original, including explicit rowids, and require SQLite's structural quick check
   to succeed. A missing row, extra row, changed value or changed key rejects publication.
4. Close both SQLite connections, then atomically rename the complete candidate over
   the original. A reader already admitted on the original inode can finish reading its
   complete generation. New readers open the complete replacement.

The implementation retains the original schema rather than relying on an unspecified
rowid effect from a generic compactor. SQLite documents that `VACUUM` can change rowids
when a table has no explicit integer primary key. [SQLite VACUUM documentation](https://www.sqlite.org/lang_vacuum.html).

## Worked example and failures

Suppose two source observations have identical payloads but occurrence keys 101 and
104. Another observation has key 109 and a different payload. Their dictionary keys
may be shared, but all three occurrences must remain in order: 101, 104, 109. The copy
inserts those exact keys, so neither contiguous renumbering nor payload deduplication
can erase or reorder them. Membership rows retain their own independently sparse keys.

| Interruption boundary | Durable cache | Next invocation |
| --- | --- | --- |
| During a table copy | Complete original; private partial candidate | Remove abandoned staging and retry if space still warrants it. |
| During validation or after connection closure | Complete original; private candidate | Remove abandoned staging and retry. |
| After atomic replacement | Complete verified candidate | Use the compact cache; remove any abandoned empty staging directory. |

Ordinary storage or validation errors during compaction are logged with their exception
and leave synchronized cached data available. They do not turn a successful source
synchronization into a pipeline failure. Source authentication and direct-source fallback
continue to follow the [parsed-cache contract](parsed-source-cache.md).

## Costs and limitations

For `B` live payload bytes and `N` table rows, copying and validation read `O(B + N)`
data, with additional SQLite index insertion costs. Memory is bounded by SQLite's page
caches, cursor state and a small number of individual rows; the largest individual
geometry or attribute payload still needs to fit in memory. Compaction temporarily
needs space for a complete live candidate beside the original file. It runs once after
synchronization when the thresholds justify it, rather than on every cached lookup.

Exact comparison protects stored values and occurrence identity. SQLite's type and
serialization behavior, filesystem replacement and cooperative file locks remain
trusted adapter boundaries. The protocol does not authenticate source truth or repair
arbitrary cached corruption; it preserves the existing validated cache and its fallback
behavior. The read transaction excludes changes by the cooperating writer path during
copying. Callers of lower-level synchronization helpers must already own exclusive
writer access.

## Implementation and verification

Implementation: [compaction.py](../../src/peri_scribe/geo/compaction.py) and
[`ensure_database_current`](../../src/peri_scribe/geo/database.py).

The [ParsedCacheCompaction model](../../tests/formal/tla/ParsedCacheCompaction.tla)
checks six table copies over six ordered payload sequences, including repeated values.
It admits corrupted staged payloads, failure at every prefix, complete validation,
connection closure, publication and independent reader observations. TLC explores 1,542
distinct states and checks durable-content preservation, reader completeness and
validated publication. It assumes cooperating writer exclusion and atomic replacement;
it does not prove SQLite or the operating system.

[Conformance](../../tests/formal/conformance/test_cache_compaction.py) compares 60 real
compaction executions against continuous paths through the complete TLC graph. It
observes table copies, validation, connection retirement and publication, injecting
interruptions at eight boundaries and corrupting memberships before validation. It
compares every original/candidate table value and sparse occurrence key, and keeps an
actual SQLite reader open through replacement.

[Ordinary regressions](../../tests/tests/standard/peri_scribe/geo/test_compaction.py)
cover storage reduction, unchanged values and ordering, active readers, WAL and threshold
skips, failed publication, failed maintenance, actual cross-process lock exclusion and
three real process-termination/recovery boundaries. The existing parsed-cache and
normalized-cache conformance checks continue to cover synchronization, receipts,
dictionary references and fallback.

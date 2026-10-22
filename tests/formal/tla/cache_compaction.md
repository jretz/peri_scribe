# Parsed-cache compaction

`ParsedCacheCompaction.tla` covers exact staged table copying, candidate validation,
connection retirement and atomic replacement of a disposable parsed-source cache.
The algorithm contract and complexity assessment are in
[ordered cache compaction](../../../docs/algorithms/parsed-cache-compaction.md).

## State and properties

The configuration has six tables and six ordered symbolic payload sequences, including
duplicates. A copy may preserve a table or introduce an extra symbolic observation.
Validation accepts only a complete candidate equal to the durable original. Closing
SQLite handles is a separate action before publication. Failure can occur at any copy,
validated or closed boundary; independent observations read the durable file.

| Property | Meaning |
| --- | --- |
| `TypeOK` | The bounded lifecycle and copied-table count remain in their stated domains. |
| `DurableContentsPreserved` | Every durable table retains the exact original ordered payload. |
| `ReadersKeepCompleteData` | Readers observe complete original contents through compaction and failure. |
| `OnlyValidatedDataPublishes` | Validation, closure and publication require all staged contents to match. |

TLC checks **1,542 distinct states** over six initial valuations. These finite safety
checks do not establish unbounded liveness or library correctness. The model assumes
exclusive cooperating writer ownership, immutable pinned source contents during a
copy, exact value transfer by SQLite and atomic same-filesystem replacement. It excludes
power-loss durability, storage corruption after validation and uncooperative writers.

## Implementation mapping

- `geo.compaction.copy_table` maps to `Copy`; explicit source rowids preserve occurrence
  identity, including gaps, independently of dictionary sharing.
- `geo.compaction.validate` maps to `Validate`; every complete table and SQLite's
  structural quick check must pass.
- Returning from `geo.compaction.prepare` maps to `Close`; both SQLite handles are closed.
- `Path.replace` in `geo.compaction.compact` maps to `Publish`.
- Exceptions and process termination before publication map to `Fail`; cleanup of the
  unpublished candidate changes no durable source-cache contents.

`geo.database.ensure_database_current` owns a persistent neighboring file lock across
synchronization, corruption recovery and optional compaction. The same lock excludes
another cooperating process while an inode is replaced. WAL caches skip compaction.
The next owner removes only abandoned staging directories bearing that database's
reserved prefix. Those file-lock and cleanup boundaries are adapter obligations.

## Executable evidence

[`test_cache_compaction.py`](../conformance/test_cache_compaction.py) consumes the
complete checked graph and follows **60 concrete executions** through continuous
successor paths: six original sequences, eight interruption boundaries, successful
publication and rejected membership corruption. Each symbolic table identity denotes
the complete original ordered SQL rows, including implicit keys, rather than a receipt
alone. The adapter observes actual copy, validation, closure and replacement boundaries;
it retains all compatible full model states across the complete execution.

The standard compaction regressions independently check actual disk reduction, exact
values and sparse keys, an admitted SQLite reader, failed replacement, skipped WAL and
small caches, and maintenance failure fallback. A separate process probes real file-lock
exclusion. Three subprocess cases call `os._exit` during table copying, after SQLite
closure and after replacement; a fresh invocation preserves complete values and reclaims
the abandoned staging directory. These process tests do not model power loss.

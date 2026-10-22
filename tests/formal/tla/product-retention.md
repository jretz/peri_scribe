# Prepared-product retirement

`ProductRetention.tla` models optional cleanup after the owning application's product
transaction has committed. It separates logical retirement from physical compaction so
cleanup failures cannot undo completed retained products. The
[algorithm note](../../../docs/algorithms/product-cache-retention.md) defines the
retention policy and compaction thresholds.

## Checked state and properties

The finite model contains three dependency contexts with two immutable product tokens
each. A token stands for the complete context, namespace, key, checksum, and payload
row. Four admitted-context subsets include the outer context and zero or more nested
contexts. One maintenance writer and one independent reader interleave over deletion,
commit, rollback, deletion failure, successful or deferred compaction, and reader
open/close actions. The configured exploration checks 140 action-prefix states.

Application products are initially committed. `pending` is the writer's current view;
`durable` is the latest committed state; `reader` records an explicitly pinned SQLite
snapshot. The `footprint` abstraction counts allocated row slots rather than actual
SQLite pages. Compaction can reduce that allocation without changing logical products.

The invariants require that every admitted product survives, no product is invented,
committed retirement removes every obsolete context, uncommitted retirement stays
invisible to independent readers, readers observe whole committed states, and physical
allocation covers logical contents. Optional rollback and compaction deferral have no
liveness obligation. The model allows all contexts to be retained, covering a pass that
has no obsolete generation to remove.

## Connection to implementation

[`test_retire_contexts_matches_every_checked_maintenance_prefix`](../conformance/test_product_retention.py)
reads the complete checked TLC corpus and replays every retained action prefix against
an independent SQLite database. Production `retire_contexts` performs deletion and
`compact_store` performs `VACUUM`; real connection commit, rollback, and explicit reader
transactions supply the corresponding boundaries. The test compares uncommitted writer
rows, independently committed rows, and any pinned reader snapshot with the exported
formal state. Distinct binary payloads make changes to values observable as well as
changes to membership. SQLite's read-only pragma injects a real deletion error.

Six hard-process checks invoke production `maintain_store` and terminate immediately
after deletion, after retirement commit, or after compaction. Each boundary is tested
with `os._exit` and `SIGKILL`. A fresh interpreter opens the same database and compares
recovered rows with the matching checked prefix. A crash before retirement commit uses
the model's rollback result; the other boundaries require the committed selected rows.
The common crash adapter verifies actual termination status and that normal Python
cleanup did not run.

The [ordinary scope tests](../../tests/standard/spatial_data/test_product_cache_retention.py)
cover admission of nested contexts, application failure, cache disabling, exact complete
row equality, compaction thresholds, real-reader contention, and physical size reduction.
They check that a partial retirement failure preserves newly committed application
products, connecting the maintenance model's initial state to the outer scope's commit.
The existing [ProductCache](cache.md) model continues to cover application product and
manifest construction before this maintenance phase.

## Assumptions and limits

SQLite provides transaction isolation, atomic commit and rollback, crash recovery, and
logical row preservation during `VACUUM`. The reader interleavings model the default
rollback-journal mode: a pinned reader can block the writer's commit or compaction.
The model does not establish all SQLite journal modes or independently evolving
concurrent writers. Production callers retain their existing cooperating pipeline lock.

Three contexts and six rows are finite bounds, not an unbounded proof. Contexts and
products are already well formed; checksum validation, exact dependency identity and
cache-miss recomputation are covered by the existing cache contract and its consumers.
The model abstracts allocated pages and temporary disk use, so it proves no byte limit
or compaction latency. Corrupt SQLite files, arbitrary Python executions, SQLite's own
implementation, and power-loss durability remain outside these checks. Contention or
storage failures may defer optional cleanup indefinitely.

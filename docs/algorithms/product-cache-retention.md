# Prepared-product context retention

## Contract and assessment

The prepared-product database retains the dependency contexts used by its most recent
successful owning scope. Older application or runtime fingerprints cannot produce a
hit in that scope, so keeping their products only helps if a future execution returns
to an old fingerprint. Retirement trades that possible reuse for bounded accumulation
of obsolete contexts. Returning to a retired context is an ordinary cache miss; callers
recompute the same KMZ, updates, and reports from authoritative inputs.

The inputs are the SQLite product database and every dependency context admitted by an
outer scope or a same-path nested scope. Retention preserves every namespace, key,
checksum, and payload in those contexts, including products that were not read during
this execution. A nested scope at another database path has its own retention decision.
The [typed product cache contract](product-caching.md) still governs whether a retained
row is reusable.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Successful scope completion selects retained contexts, and deferred compaction carries free pages into later runs. |
| Rule interaction | 2 | Application success, cache availability, nested contexts, and compaction thresholds jointly permit cleanup. |
| Mathematical reasoning | 1 | Set selection preserves complete retained rows; physical reclamation uses standard SQLite transactions. |
| Scale and representation | 2 | Context-prefix deletion and page compaction avoid retaining obsolete generations in a large `WITHOUT ROWID` table. |
| Failure and concurrency | 3 | Application commit, retirement commit, and physical compaction are separate durable boundaries with concurrent readers. |

**Complex: 10.** Cleanup must never turn a valid retained product into a wrong hit or
undo completed application products. The cache remains disposable, so failure can defer
cleanup without failing publication.

## Retire only after completed products commit

One outer scope owns the connection. Same-path nested scopes share its mutable set of
admitted contexts, even while they temporarily select different fingerprints or force
reads to miss. The set records use over the whole scope rather than just its final
context. Keeping only the final nested context would discard products prepared by the
outer scope and earlier nested consumers.

A cache statement error in a same-path nested scope also disables its owner. Finishing
that nested scope cannot restore cache availability, even if the underlying connection
recovers before the outer scope exits. Earlier successful application writes may still
commit, but that execution skips maintenance.

Successful exit has three separately recoverable steps:

1. Commit the application products using the existing cache transaction. An application
   exception, failed commit, or disabled cache skips maintenance.
2. Enumerate stored contexts and delete those outside the retained set in a new SQLite
   transaction. Commit all retirement together. A SQLite error rolls it back and
   defers cleanup.
3. Compact physical storage with SQLite `VACUUM` when free pages justify it. This starts
   after retirement commits, so compaction failure cannot undo completed products or
   expose a partly retired context set.

The table's primary key begins with the context, allowing each obsolete context to be
deleted as an indexed range. Context values are SQL parameters. All obsolete context
names are collected before deletion; mutation cannot change the enumeration cursor's
remaining observations.

Compaction runs when retirement freed any pages. If retirement succeeded previously but
compaction was deferred, a later run retries when free pages occupy at least 16 MiB and
at least one quarter of the database's allocated pages. The same rule can reclaim space
left by ordinary within-context pruning. Both thresholds apply to free SQLite pages,
not estimated Python payload sizes. Small leftover space remains reusable by SQLite and
does not justify rebuilding the entire file on each execution.

`VACUUM` preserves logical rows while rebuilding physical allocation. The products table
uses `WITHOUT ROWID`, so no caller depends on an implicit row identifier that compaction
could renumber. Its checksums and payload bytes remain unchanged.

## Examples and interruption boundaries

Suppose a database contains contexts `old`, `current`, and `map-policy`. The outer scope
uses `current`, and one nested consumer at the same path uses `map-policy`. Retirement
keeps both contexts, including unused namespaces, and removes all rows of `old` in one
transaction. If a later run returns to `old`, its lookups miss and its completed products
replace the retired cache state through the ordinary preparation path.

An application failure is different from an obsolete context. If the outer scope raises
after writing a new product, the scope closes without committing and does not retire
anything. If application commit succeeds but a deletion fails halfway through retirement,
SQLite rolls back the deletion transaction while preserving those newly committed
products. Combining these two transactions would unnecessarily discard useful completed
work when optional cleanup failed.

| Interruption or contention | Durable rows and next action |
| --- | --- |
| Before application commit | Existing committed rows remain; no maintenance runs. |
| During retirement, before its commit | SQLite recovery retains the entire preceding committed context set. |
| A reader blocks retirement commit | The retirement transaction rolls back; application products remain committed. |
| After retirement commit, before compaction | Only retained contexts remain; freed pages can be reused or compacted later. |
| A reader or storage error blocks compaction | Logical rows remain retained; a later eligible run retries physical reclamation. |
| After successful compaction | Retained logical rows are unchanged and the database occupies fewer allocated pages. |

Existing readers use SQLite's isolation rules. In the default rollback-journal mode,
a reader holding a snapshot can prevent retirement commit or compaction, and the short
existing connection timeout makes maintenance defer. Cleanup does not replace the
database pathname behind open connections. Production execution retains the existing
cooperating pipeline lock; this policy does not introduce cross-process leases for
contexts belonging to unrelated writers. Such writers can cause misses or contention,
but a lookup still requires its exact context, namespace, key, and checksum.

## Costs and limits

Let R be stored rows, C stored contexts, D bytes belonging to retired contexts, and A
allocated database bytes. Enumerating distinct context prefixes can inspect O(R) index
entries and retains O(C) names. Indexed range deletion visits the obsolete rows and
their pages; its storage work depends on D and SQLite's tree maintenance. Compaction
rewrites the surviving database and has storage costs proportional to its allocation,
bounded by O(A). SQLite may need substantial temporary disk space while rebuilding;
failure leaves the already committed logical rows usable.

The scope retains O(C) context names in addition to the existing configured 8 MiB SQLite
page cache. That cache setting does not bound all SQLite, operating-system, or process
memory. Physical compaction may be deferred indefinitely by failures or competing users.
No space or completion guarantee assumes that those conditions eventually disappear.

After successful retirement, obsolete contexts no longer accumulate. Products within a
retained context can still grow, and admitting several nested contexts deliberately
retains all of them. This is a retention policy for obsolete dependency generations,
not a fixed limit on total cache bytes. The threshold for retrying deferred compaction
is a resource tradeoff; it does not affect output equivalence.

Retaining several historical contexts would improve reuse during frequent application
rollbacks but preserve proportionally more obsolete products. Deleting old contexts on
entry would reclaim space sooner but sacrifice them even when the new run failed.
Copying retained rows into a replacement database could build a compact file directly,
but would require a separate connection-lifetime and replacement protocol. In-place
SQLite transactions and `VACUUM` reuse the existing isolation and recovery contract.

## Implementation and verification

[`product_cache.scope`, `retire_contexts`, and `maintain_store`](../../src/spatial_data/product_cache.py)
own context admission, logical retirement, and physical reclamation.
[Ordinary tests](../../tests/tests/standard/spatial_data/test_product_cache_retention.py)
compare exact retained rows, exercise old-context recomputation, nested paths, partial
deletion failure, a live reader, disabled-cache fallback, and deferred compaction retry.
They also verify that a database dominated by obsolete payloads physically shrinks.

The [ProductRetention model and conformance note](../../tests/formal/tla/product-retention.md)
describe the checked finite transition system, actual SQLite replay, and hard-process
crashes at the three cleanup boundaries. The model was checked before implementation.
SQLite atomicity and isolation, correct dependency contexts, and deterministic cache-miss
recomputation are assumptions. The checks establish neither arbitrary Python refinement
nor filesystem durability after power loss.

# Persistent product caches

`CacheDefinitions.tla`, `CacheRead.tla`, and `ProductCache.tla` correspond to
`spatial_data.product_cache` and `spatial_data.row_index`. They extend the geography
publication model into the disposable SQLite cache that accompanies the published files.

## Read correspondence

`CacheRead.cfg` checks all 12,288 combinations of two authoritative artifact generations,
absent or either-generation manifests, three independently present payloads, one damaged
payload or none, every requested subset, matching/mismatching dependency contexts,
forced/unforced reads, and valid/invalid manifests. Generation one orders groups 1, 2;
generation two orders groups 3, 2, retaining one shared content-addressed group.

The reader may return a miss or exactly the requested groups of the authoritative
generation in publication order. Missing or damaged requested payloads require fallback.
Damage to an unrequested group does not prevent a valid partial selection. An empty
selection is a successful result only when the manifest and generation remain valid.
Forced reads and mismatching dependency contexts cannot reuse data.

`test_read_matches_all_checked_cache_selections` exports the checked TLC valuations and
compares each answer against real `row_index.read` calls over a temporary SQLite store.
Each symbolic group contains two ordered concrete rows, making both group ordering and
row ordering observable. Nested scopes verify that an unforced child cannot override an
ancestor's forced reads. Corrupt payloads are written through `product_cache.put`, so
the row-index content digest must reject them even with a valid storage checksum.

## Transaction correspondence

`ProductCache.cfg` checks 150 action prefixes, including one interruption/retry and a
SQLite statement failure at each construction step. Payload writes, manifest replacement,
pruning, and transaction commit are separate actions. The required properties are that
the visible manifest always has its complete payload set and that committed cache reads
cannot return rows from the wrong artifact generation. A failed statement may leave
earlier writes in the transaction; the model permits those to commit after cache reuse
has been disabled, matching the implementation.

`test_scope_matches_every_checked_transaction_prefix` replays every exported action
prefix against the real cache operations. It inspects uncommitted writer state and a
separate reader's committed state. SQLite's read-only pragma injects real statement
errors; exceptions exercise scope rollback. These are checks of the application's use
of transactions, with SQLite's transaction isolation and atomicity assumed.

## Boundaries

The model assumes complete initial generations and that callers supply correctly
normalized rows, complete dependency keys, and an authenticated authoritative artifact
checksum. It does not prove that every caller includes every semantic dependency in its
fingerprint. Hash collisions, SQLite internals, serialization implementation, unrelated
concurrent database writers, and filesystem durability after power loss remain outside
the model. Tests retain real serializers, checksums, and SQLite behavior at the bridge.
Adaptive bulk fallback remains an optimization covered by ordinary tests. Cache misses
are allowed, so no liveness claim requires the optional cache to become available.

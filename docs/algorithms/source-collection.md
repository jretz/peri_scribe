# Incremental source collection

Fire feeds preserve observations in append-only snapshots. Collection must discover
changes even when a provider fails to advance an individual feature's edit timestamp,
and an interrupted write must never appear to be a completed observation.

## Contract and assessment

Inputs are configured ArcGIS feeds, their metadata and query responses, and ordered
saved snapshots. Outputs are complete new GeoPackages and a change result. Snapshot
serial order determines which stored feature is current. Full collection remains a
recovery mechanism because metadata, ID queries, and feature queries are separate
provider operations.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Current features are reconstructed from ordered observations. |
| Rule interaction | 2 | Changed, missing, and status-flipped IDs require distinct evidence. |
| Mathematical reasoning | 1 | Set union and keyed last-occurrence selection are standard operations. |
| Scale and representation | 2 | Current-state caches avoid repeatedly reading every snapshot. |
| Failure and concurrency | 3 | Independent feed workers and staged publication must survive interruption. |

Total **10: complex**. Source correctness also determines all downstream histories.

## Candidate selection

![Three sources of incremental candidates](assets/source-candidates.svg)

The candidate union covers three different ways a row can become newly relevant. The
queries share an ID namespace but do not share a provider transaction.

1. With no stored snapshots, query the complete layer. An explicit full fetch also
   queries the complete layer, then removes rows already stored identically.
2. Incremental collection derives a cutoff from usable stored edit times with an
   overlap allowance, then queries recently changed IDs.
3. Query all live IDs and subtract stored IDs. This finds newly published rows carrying
   old timestamps.
4. Query stored-active IDs for known inactive status literals. This catches supported
   status flips whose edit time did not advance.
5. Union and sort candidate IDs, fetch their features, and remove observations already
   represented by normalized attributes and equivalent geometry.

For stored IDs `{1, 2}`, changed IDs `{2}`, live IDs `{1, 2, 3}`, and a detected status
flip for `1`, the union is `{1, 2, 3}`. Row `3` would be missed by a timestamp-only
query. A removed live row does not delete historical evidence.

## Publication and current state

The coordinator waits for admitted feed workers. Each worker owns its connection and
feed directory. An existing completed snapshot with the same metadata edit time can
authorize an incremental skip; full collection bypasses this shortcut. When collecting
a new observation, the worker publishes it before advancing the disposable cache:

1. Read and compare provider evidence to construct the changed feature frame.
2. Write and close `snapshot.gpkg` under a private staging directory, where snapshot
   discovery cannot see it.
3. Rename the completed file to its final snapshot path. Only now may discovery or
   edit-time reuse see the observation.
4. Advance the current-state cache. If interruption leaves it behind, recover from
   completed snapshots as described below.

An abandoned staging file never earns a final snapshot name. A discoverable path
therefore denotes a completed write under the process-failure and cooperating-writer
assumptions. A stale cache loses acceleration; the completed observation remains
authoritative.

The current-state cache keeps the last row per object ID. Reads accept it only when its
covered serial equals the newest snapshot serial. Updates may extend a cache covering
the newest or immediately preceding snapshot; any larger gap rebuilds from snapshots.
For example, if snapshots 8 and 9 were published but the cache still covers 7, appending
only snapshot 9 would lose changes first observed in 8. Reconstruction closes that gap.
Cache failure leaves the completed source observation available.

## Bounded network retries

The ArcGIS adapter retries only recognized rate limits and transient connection,
timeout, or chunked-transfer failures. Structured ArcGIS error payloads take precedence
over loose text matching. HTTP 429 responses accept an integer `Retry-After` header;
an absent or unusable hint falls back to 60 seconds. Structured text is parsed as JSON
before applying loose patterns, so key ordering does not discard a valid instruction.

Rate limits use their selected delay. Other transient errors use exponential waits
starting at two seconds and capped at 30 seconds. Four retries means at most five
attempts; an unrecognized error propagates immediately. For example, a timeout followed
by a 429 with an eight-second hint waits two seconds after the timeout and eight after
the 429. Applying exponential delay to both would ignore the provider's instruction.
The retry count bounds attempts, not total wall-clock time: server hints are not capped
by the transient-backoff cap, and each request has its own timeout.

## Costs and limits

For `S` stored observations and `L` live IDs, reconstruction takes work proportional to
the stored rows and their geometry/attribute decoding. Candidate set operations use
`O(L + S)` ID work and storage in the worst case; exact row comparison adds geometry
cost. Warm current-state reads reduce snapshot I/O, but full live-ID queries remain.
Network request counts and provider pagination belong to the ArcGIS adapter.

This protocol cannot guarantee a transactional snapshot of a changing remote service.
A settled provider and later successful full fetch are recovery assumptions. Timestamp
skipping cannot detect every provider edit that leaves layer metadata unchanged. The
protocol preserves history rather than implementing remote deletion mirroring.

## Implementation and verification

- [Collection](../../src/peri_scribe/sources/fetching.py),
  [current state](../../src/peri_scribe/sources/feed_state.py),
  [snapshot discovery](../../src/peri_scribe/sources/snapshots.py), and
  [change detection](../../src/peri_scribe/sources/changes.py).
- [Retry policy](../../src/arcgis_access/retry.py) and
  [retry tests](../../tests/tests/standard/arcgis_access/test_retry.py).
- [Incremental collection conformance](../../tests/formal/conformance/test_incremental_collection.py),
  [feed cache conformance](../../tests/formal/conformance/test_feed_cache.py), and
  [snapshot publication conformance](../../tests/formal/conformance/test_snapshot_publication.py).
- [SnapshotCollection](../../tests/formal/tla/SnapshotCollection.tla),
  [FeedCache](../../tests/formal/tla/FeedCache.tla),
  [FeedCoordinator](../../tests/formal/tla/FeedCoordinator.tla), and
  [SnapshotPublication](../../tests/formal/tla/SnapshotPublication.tla).
  The [TLA+ inventory](../../tests/formal/tla/README.md) states finite bounds and
  environmental assumptions; these checks do not prove remote-provider behavior.

See [source validation](source-validation.md) for comparison semantics and
[pipeline publication](pipeline-publication.md) for durable rebuild intent.

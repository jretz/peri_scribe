# Snapshot publication and changing feeds

## Raw snapshot publication

`SnapshotPublication` models the authoritative feed GeoPackages produced by
`fetch_feed_snapshot` in `src/peri_scribe/sources/fetching.py`. It covers the metadata
shortcut, staging an entire snapshot, atomically publishing its filename, then updating
its derived current-state cache. `sources.snapshots.existing_source_files` and
`snapshot_path_for_last_edit_timestamp` recognize published files by their filenames.

The checked invariants establish that every discoverable snapshot is complete, an
existing snapshot is preserved, cache acknowledgment follows publication, and a
full-mode write appends even when the source timestamp matches an existing snapshot. A
process interruption can leave staging bytes behind; staging filenames cannot be parsed
as source snapshots. A cache-write failure cannot retract the authoritative snapshot.

For every collection that passes the metadata shortcut, this publication model assumes
content comparison produced changed observations to write. An unchanged full collection
can return the existing snapshot without appending; `SnapshotCollection` separately
checks that deduplication behavior.

The safety configuration explores 227 states: zero or one existing snapshot, matching or
different timestamps, full or incremental mode, three serialized chunks, and at most one
interrupted attempt. Its liveness configuration requires future retry and progress
through writing, publication, and cache handling after that interruption. These are
finite bounds; the model does not prove arbitrary repeated failures or writer races.

The implementation writes `snapshot.gpkg` inside a temporary directory on the target
filesystem, then replaces the final timestamp-bearing path after the writer returns. The
staging filename matters because discovery recursively scans `*.gpkg`; a temporary
subdirectory alone would still expose a timestamp-bearing filename. Ordinary exception
cleanup removes staging data; hard termination can leave an ignored directory.

`test_snapshot_publication.py` replays all six initial modes with every interrupted
prefix and a successful retry, reads completed GeoPackages, verifies that earlier files
remain byte-identical, and checks orphan discovery. The ordinary regression
`test_fetching_snapshot_publication.py` was confirmed failing before the fix: partial
bytes at the final filename were accepted as an existing source snapshot.

The contract assumes cooperating writers hold the existing pipeline lock, prior
snapshots are valid, the serializer completes its output before returning, and same
filesystem replacement is atomic. It does not establish power-loss durability, validate
preexisting corrupt snapshots, or automatically remove orphan directories. An
interrupted process after publication but before cache update leaves a complete
authoritative file; the separately checked current-state cache rebuilds from snapshots
when necessary.

## Remote mutations during collection

`SnapshotCollection` extends the stable-view assumptions of the Lean incremental
collection policy with transitions between metadata, changed-ID, all-ID, and
feature-body queries. It maps to `fetch_feed_snapshot`, `fetch_feed_dataframe`, and
`feed_state.latest_features_by_object_id`. It allows row addition, removal, replacement,
and timestamp eligibility to change independently, including edits that leave the layer
metadata marker unchanged. An empty body after an ID query contributes no snapshot.

The invariants establish that returned observations came from the body query, the
selected IDs include both queried changes and previously unseen IDs, and append-only
collection preserves stored history when source rows disappear. A metadata marker names
the marker observed before collection; it does not certify that several later queries
shared one transactional source view.

An independent `Settle` action represents the provider becoming quiescent. A later
`Recover` action starts a full fetch, bypassing the metadata shortcut. Once that full
fetch finishes, every currently present remote row has its current value in storage,
even if earlier queries missed it or the metadata marker never changed. Liveness assumes
eventual provider quiescence, a future full invocation, and successful progress of its
queries and writes. The existing full-fetch scheduling checks cover local due/overdue
selection; eventual future invocations and successful external service responses remain
environmental assumptions. No new metadata recheck would establish transactionality when
the provider can edit rows without changing its marker.

The safety and liveness configurations each explore 3,732 states. Bounds are two object
IDs, absent or two possible row versions, a nonempty source, two metadata markers, one
remote mutation, one initial collection, and one full recovery. Queries return the rows
they observe without truncation. Feature pagination within one query, inconsistent
provider responses, transient versions removed before collection, source truth, and
infinitely changing feeds remain outside this model. A recovery full fetch retains
historical rows deleted remotely; its completeness claim concerns currently present
rows, not exact equality of object sets.

`test_snapshot_collection.py` replays all 177 distinct initial outcomes through real
metadata skipping, query routing, GeoPackage serialization, current-state cache updates,
and later full collection. Ninety-seven outcomes contain a missed or stale current row
before recovery. The checked recovery relation is matched by the exact previous saved
rows, final source rows, and metadata marker; every real recovery result equals that
relation. These executions show why periodic full collection is necessary even with
otherwise successful incremental invocations. These race fixtures keep stored rows
inactive, so they exercise changed-ID and missing-ID queries but omit the separate
inactive-status query for previously active rows. The stable-view union of all three
routes has separate Lean conformance; races within the status query and feature
pagination are not checked by this temporal fixture.

# Ingestion and worker contracts

These models cover source recovery and cancellation outside derived pipeline stages.
Their configurations participate in the ordinary formal task, including liveness.

## FeedCache

`FeedCache.tla` checks `sources/feed_state.py::write_current_state`. It enumerates three
ordered snapshots, two object identities, two values, every cache prefix (including a
cache ahead of the authoritative snapshots), and readable/unreadable caches. A cache can
accelerate an update only when its serial identifies the newest or immediately preceding
existing snapshot. Other prefixes require complete snapshot replay. The newest snapshot
wins duplicate object identities. Staging and publication are separate transitions;
interruption can retry without exposing the incomplete candidate.

The safety configuration checks that every candidate and every published cache equal
independent recursive replay of the authoritative snapshots. It explores 4,800 states.
The liveness configuration requires preparation to progress and successful publication
to occur eventually when retried; perpetual write failure has no completion guarantee.

The conformance test exports all 1,536 candidate states from TLC and exercises actual
production source selection, dataframe merging, cache replacement, and cleanup. It
replaces GeoPackage serialization with model-provided dataframes while retaining real
filesystem rename operations. Ordinary regression tests use real GeoPackages and cover
missed cache updates, rollback to earlier snapshots, unreadable caches, interrupted
writes, and successful retry.

The snapshots are immutable within a cooperating writer's update and contain no deletion
records. Cache prefixes initially describe previously completed writes. Silent arbitrary
corruption of a readable cache, mutation or reuse of snapshot serials, unrelated
writers, and old cache files that were already incorrectly labeled current are outside
this contract. Removing a derived cache causes reconstruction from snapshots. Last-
write-wins is checked over this finite domain, not proved for unbounded histories.

## StaticDownload

`StaticDownload.tla` checks `sources/downloading.py::completed_download`, used by single
archive downloads, converted state combinations, and streamed state combinations. The
model separates three staging chunks, completion, atomic rename, observation, and an
interruption followed by retry. Existing output is either absent or previously complete.
An observer can never see a partial reusable output. Both configurations explore 19
states; liveness assumes finite failure and weak fairness of remaining work.

The conformance test replays every possible interruption prefix (including after all
chunks but before rename) through the production context manager and compares visibility
and successful output length with TLC states. Ordinary regressions interrupt actual
GeoPackage writes in all three coordinating paths, check that no partial output remains,
and then retry successfully. Per-state conversions use a separate staging subdirectory
so a state name cannot overwrite the aggregate. A real-file regression combines two
states when the aggregate has the later state's name and verifies all ordered rows.
Additional existing tests cover output reuse.

The contract assumes same-filesystem atomic rename, one cooperating writer, successfully
closed conversion outputs, and immutable static sources. It does not validate geospatial
meaning or identify partial output left by older implementations. The existence check
cannot distinguish such files from complete downloads; suspected partial files must be
removed before re-downloading. Ordinary exception and cancellation tests execute
cleanup; abrupt process termination may leave private staging directories, which are not
reusable output paths. Power-loss durability is not established. An empty or otherwise
failed conversion is not a successful publication.

## WorkerLifetime

`WorkerLifetime.tla` checks `concurrency.py::{run_blocking,finish_worker,cancellable}`
and an enclosing semaphore's ownership. A blocking worker, cancellation handler, chunk
reads, worker exit, and owner return are separate actions. Cancellation wins over a
concurrent worker result or error, while resources and the concurrency permit remain
held until worker exit. Reads cannot start after the cooperative stop signal; bytes
arriving during cancellation cannot be delivered afterward. The cancellation count
saturates at two so arbitrary additional cancellation remains enabled without growing
the finite state space.

Both configurations explore 90 states, including two read opportunities, worker success
or failure, and cancellation before or after worker exit. Liveness requires blocking
reads and the worker to finish and the owner to be scheduled; it makes no claim that
Python can forcibly terminate a stuck thread.

Conformance compares all six distinct cancellation/failure outcome combinations with
real blocking threads, asyncio cancellation (including five repeated requests), and an
enclosing semaphore, asserting that cancellation cannot release the permit while the
worker still runs. A separate checked late-read state is replayed with cancellation
inside the iterator's read. The tests exercise the optional cooperative signal; existing
ordinary tests also cover workers without one. This is bounded scheduling evidence, not
a proof of the Python event loop, thread runtime, or arbitrary callers' resource
ownership.

# Document publication and concurrent feed collection

## Complete published documents

`DocumentPublication` checks the protocol shared by `output.write_document`,
`output.write_fire_scores_ccdf`, and `report.markdown.render_markdown_report` through
`output.publication_path`. It applies independently to fire index JSON, score JSON,
the score distribution HTML page, and the Markdown report.

The model separates three private writes, closing the staged file, replacing the
canonical name, reader observations, and one interruption followed by retry. Initial
publication can be absent or contain an older complete generation. Interrupted writes
can leave private staging bytes, but only the canonical name is public. Checked
properties require readers to observe absence or a complete generation, preservation
of previous contents before replacement, and visibility of the new contents after
success. Weak fairness of writing, closing, and replacing establishes completion once
the bounded interruption is exhausted.

The safety and liveness configurations explore 70 distinct states. The three chunks
abstract arbitrary partial byte writes; this is a bounded protocol check, not a proof
for an arbitrary filesystem. Atomic same-filesystem replacement and ordinary local
filesystem reads are assumptions. Process termination is covered; power-loss durability,
directory synchronization, storage corruption, and multi-file generation atomicity are
not claimed. Serialization happens before replacement; invalid serialization that
returns normally is outside this publication property.

`conformance/test_document_publication.py` exports the checked TLC states and checks the
real canonical path during each of three flushed writes and on both sides of replacement.
Its 56 scenarios cover all four public writers, absent/previous files, interruption at
six boundaries, successful publication, and subsequent retry. JSON uses the actual JSON
encoder and all successful bytes match production output exactly. Controlled exceptions
exercise cleanup rather than operating-system process killing; the model also permits
abandoned private staging. The independent ordinary regressions confirmed truncated JSON,
HTML, and Markdown before the writers adopted the checked staging protocol.

## Whole-collection failure composition

`FeedCoordinator` maps to `pipeline.run_fetch_stage`, the collection portion of
`pipeline.run_gated_fetch_stage`, `pipeline.fetch_fire_sources`,
`sources.fetching.fetch_all_feeds`, `collect_feeds`, `collect_one_feed`, and
`concurrency.run_blocking`. Individual feed snapshot publication is covered separately
by `SnapshotPublication`; this model composes worker outcomes and their persisted
effects with collection-level control.

Three feeds share capacity two. Each may be unchanged, publish a snapshot, report an
expected source error, fail fatally before publication, or fail fatally after publication.
Normal source errors permit siblings to continue. Fatal errors initiate task cancellation;
already running threads can still publish, and the coordinator must join them before
returning. Queued workers can start until cancellation takes effect. Recovery intent is
persisted before workers begin, indexing and acknowledgment are separate actions, and
index publication can fail. Full/incremental fetching, previous recovery obligations,
and immediate/deferred indexing vary independently. Process loss may occur between any
coordinator actions.

The safety and liveness configurations each explore 197,898 distinct states. The three
feeds and capacity two are finite bounds; correspondence for arbitrary feed counts and
worker limits is not proved by these runs.

Properties require bounded active workers, no unmarked published input, no retirement of
changed-input recovery, joining of active threads, complete indexing of successful
snapshots, and no full-fetch acknowledgment after any feed or index failure. Unchanged
successful incremental collection can restore earlier recovery state. Expected source
errors cannot themselves trigger sibling cancellation. Fair worker scheduling and eventual
worker termination give eventual success, failure, or process termination; no timeout or
progress guarantee is claimed for a hung SDK operation.

For deferred indexing, the terminal state is the successful collection boundary before
the publication gate decision. Pending means either durable pending stages or the durable
deferred-input marker. Gate acceptance, rejection, and later indexing are covered by the
existing publication-gate and pipeline-composition models. The full-fetch acknowledgment
is therefore deliberately absent at that deferred collection boundary. One invocation is
modeled; prior full-fetch timestamp selection, repeated recovery invocations, external
source refreshes, and power-loss durability have their own models or remain assumptions.

`conformance/test_feed_coordinator.py` compares all 2,000 input combinations with final
states exported by TLC. It retains actual asyncio tasks, semaphores, worker threads,
aggregation, pipeline recovery files, and full-fetch acknowledgment writes. Only external
per-feed operations, index I/O, and unrelated external preparation are controlled. Source
effects are real isolated files; their GeoPackage contents are abstracted here and covered
by snapshot tests. Each case verifies that all started workers finish before return,
published files correspond to worker effects, and the final outcome is reachable in the
checked model. A further 32 scenarios hold a sibling until its genuine task is cancelling,
then let it write; the resulting snapshot must retain recovery intent after the enclosing
pipeline fails. These executions provide implementation evidence rather than a refinement
proof for every Python thread schedule.

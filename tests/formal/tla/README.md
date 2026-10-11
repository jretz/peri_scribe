# System protocol models

These are executable specifications of discrete decisions and persistent publication,
cache, worker, browser, and monitor protocols. TLC explores every reachable state inside
each configuration's finite bounds. A passing configuration establishes its properties
for that model, under the assumptions below; it does not verify Python, the filesystem,
or geospatial libraries automatically.

Run `mise formal-tla` for the safety and liveness checks. Run `mise
formal-counterexamples` to reproduce the explicitly unsupported geography-pair
guarantee. The aggregate `mise formal` includes both kinds of checks and implementation
conformance checks. See [the formal verification
guide](../../../docs/formal_verification.md) for tooling and the maintenance workflow.

The matrix runs up to four TLC processes at once, each with isolated temporary metadata
and JVM storage for extracted standard modules, one exploration worker, and a maximum
1 GiB heap. Results appear as complete per-model blocks when each check finishes. Every
selected configuration runs even if another reports a failure or times out. Use
`env PERI_SCRIBE_TLC_JOBS=1 mise formal-tla` to run the matrix serially.

`models.toml` lists every executable configuration and the exact invariant expected to
fail in a counterexample configuration. An unexpected failure, a different violated
invariant, or an expected counterexample that disappears is an error. `PipelineState`
is a shared operator module, not a separate executable specification.

## Source mapping and bounds

Additional inventories describe the newer system boundaries:

- [Ownership recomputation](../lean/identity_recomputation.md): alias learning,
  allocation, acknowledgement, and stable recomputation from saved checkpoints.
- [Persistent product caches](cache.md): cache transparency, authenticated selections,
  interrupted transactions, and generation replacement.
- [Ingestion and worker protocols](ingestion.md): feed-cache replay, static download
  completion, cancellation, and resource ownership.
- [Browser and monitor protocols](../observers.md): conditional refresh, file following,
  context recovery, coverage compaction, and cached status projection.
- [Composed pipeline invocations](composition.md): selected ranges, forced work, policy
  changes, deferred inputs, and recovery after interruptions.
- [Journal file replay](journal_replay.md): real journals, compressed logs, checkpoints,
  KMZ archives, and viewer publication at checked failure boundaries.
- [Durable update validation](durable_update_validation.md): missing versus invalid
  intent, complete batch validation, and preservation of rejected checkpoint bytes.
- [Buildings construction](../ingestion_extensions.md): multiple workers, partition
  lifetime, successful validation, and complete database publication.
- [Raw snapshots and changing feeds](snapshots.md): atomic snapshot discovery, interrupted
  writes, changing remote queries, and full collection after provider quiescence.
- [Parsed source caches](parsed_cache.md): checksum/row/membership transactions, concurrent
  readers, schema rebuilds, source inventory changes, and authoritative fallback.
- [Commands and geography readers](command_readers.md): shared source-writer exclusion,
  validation recovery intent, and authenticated matching generations for consumers.
- [Document publication and feed coordination](collection_publication.md): complete
  JSON/HTML/Markdown replacement and failure composition across concurrent feeds.
- [Log rotation and seeking](../log_rotation_seeking.md): interrupted compression,
  persistent retirement receipts, and byte-offset reader completeness.
- [Readers during rotation](../reader_rotation.md): coherent monthly snapshots and
  successive monitor observations across archive replacement and late plain tails.
- [Execution assurance](../execution_assurance.md): continuous TLC transition paths and
  fresh-process recovery after actual abrupt exits and kills.
- [Observable monitor session](monitor_session.md): priority admission, immutable
  publication versions, coalesced subscriptions, and stop/close boundaries.
- [Monitor task coordination](monitor_tasks.md): shared evidence ownership, cancellation,
  publication barriers, and asynchronous descriptor shutdown.

### Run state

`PipelineState.tla` models `require_stages` and `complete_stage` in
`src/peri_scribe/pipeline_state.py`. Stages 1, 2, 3, and 4 mean geography, score, KMZ,
and reports; stage 0 represents fetch when testing a completion that cannot acknowledge
derived work. The sequence retains the source order, and requirement sets are
canonicalized on every write.

`RunState.cfg` starts with all 32 validated combinations of pending stages and the
unconditional bit. Empty pending work with unconditional true is included because
`require_stages((), unconditional=True)` permits it. Every state has all 32 combinations
of required subsets and forcing, all five completion choices, and invalid-marker
recovery to the full forced rebuild. The resulting graph has 1,248 distinct states:
32 initial states and 1,216 transition records. The properties check preservation of
requirements, sticky forcing, prerequisite ordering, and invalid-state recovery.

The `before`, `after`, and action fields are deliberately retained in each state. The
Python conformance test consumes TLC's state dump and replays every transition against
the real persistence functions. It also checks the expected action coverage so an
empty or truncated dump cannot pass. These events represent completed atomic marker
replacements; scheduler failures cover interruption before acknowledgment.

### Scheduling and locking

`RunScheduler.tla` maps to `pipeline.run`, `pipeline.run_selected_stages`, and
`pipeline_state.run_lock`. It includes two competing writers, all ten contiguous
derived-stage ranges, both forcing choices, separate stage-return and acknowledgment
steps, and at most two interruptions at arbitrary active phases. It starts with a full
forced rebuild pending. The safety graph has 5,583 states. Properties check exclusive
ownership, execution within the selected range, ordered execution, and successful
return before acknowledgment.

The modeled invocations start at a derived stage, which always records the selected
requirements before execution. Fetch's skip and invalidation decisions are covered by
`PublicationGate` and `FetchCrash`. A failed nonblocking lock attempt leaves shared
state unchanged and is represented by stuttering. Standalone commands and external
writers that ignore `.run.lock` are outside the mutual-exclusion guarantee.

`RunSchedulerLiveness.cfg` permits only complete derived-stage ranges. Weak fairness
of progress, at most two interruptions, and those full selections imply that pending
work eventually becomes empty. Its graph has 256 states. This is not a promise that a
particular competing writer eventually acquires the lock, or that repeated partial
runs eventually select omitted stages. New input invalidations are excluded during
this recovery scenario.

### Publication gate

`PublicationGate.tla` maps to `publication.decide`, `publication.mapping_decision`, and
the override expression in `pipeline.run_gated_fetch_stage`. Its 10,240 input valuations
cover eleven independent Boolean categories and signed area changes -2 through 2 with
threshold 2. They check missing-checkpoint and changed-input evidence, recovery/force
overrides, both growth and shrinkage at the threshold, and the rule that a timer alone
does not publish when no snapshots are pending. Changed city contents require publication
independently of mapped-area thresholds or timers; the content digest is abstracted as
the `citiesChanged` category.

`mappingUncertain` is the result of candidate-identity ambiguity or uncertainty in an
eligible candidate after older mappings have been discarded. It is not a raw
missing-area flag on a single older row. `olderMapping` represents the remaining
area-comparison signal being ineligible. Independent categories intentionally include
combinations that may not arise from one concrete source row. Geometry, alias
resolution, measurement units, file stamps, floating-point tolerance, and UTC arithmetic
are abstracted behind those categories; the integer area cases do not verify their
implementations.

### Update publication and journal recovery

`UpdateJournal.tla` maps to `kml.builder.create_kmz`, `fire_updates.prepare_updates`,
`fire_updates.write_updates`, `fire_updates.recover_updates`, and the atomic append and
compression functions in `logging.py`. It also includes publication invalidation in
`pipeline.run_pipeline_stage`. It distinguishes KMZ replacement, optional publication
checkpoint replacement, journal replacement, rotation-receipt replacement, archive
replacement, plain-log removal, rotation-receipt removal, batch append, mapping
checkpoint replacement, journal removal, viewer replacement, and
optional publication-checkpoint removal. The application has separate files for these
operations; the model preserves those failure boundaries.

Both configurations explore two sequential batches, at most two interruptions, and all
four combinations of empty/nonempty batches. Each batch independently chooses whether
fresh publication inputs are available and whether the invocation is gated, producing
64 initial states and 49,596 reachable states. Those choices remain fixed across a
batch's retries. The safety properties require acknowledged records to remain in a
retained log, append each nonempty batch at most once, retain its journal timestamp,
recover an earlier journal before comparing new inputs, and bring the viewer and mapping
checkpoint to the same batch after completion. `durable.appends` is history
instrumentation, not another application file. Plain and compressed copies may both
exist between archive replacement and unlink; the model does not claim globally unique
physical copies at every intermediate state.

A fresh-input build saves its publication checkpoint before acknowledging mapping
updates. A build without those inputs can still acknowledge mapping updates. If gated,
it then removes the publication checkpoint after the viewer returns; if ungated or
standalone, it retains any older checkpoint file. The retained checkpoint token cannot
acknowledge the new KMZ. The model checks these branches separately and does not require
the mapping checkpoint to be at or behind an absent or stale publication checkpoint.
`durable.publication` represents the checkpoint file's saved generation, with zero
meaning absent; reusing it as valid publication evidence additionally requires matching
the current KMZ identity, as abstracted by `PublicationGate`.

Timestamp values 1 through 3 distinguish original publication from retries. One
abstract monthly destination and a monotone `oldMonth` flag explore whether rotation
is due, including a retry after eligibility changes. This deliberately allows more
rotation timings than the calendar policy and does not prove the seven-day rule or
month-name calculation. Actual serialized records, per-fire identity, log integrity,
and archive decoding remain assumptions of the abstract model. Empty batches advance
the checkpoint without an append. Already-acknowledged builds also traverse rotation,
without creating another journal or changing their checkpoint.

`JournalReplay.tla` retains checked recovery input/output pairs for actual-file
conformance. The [journal replay inventory](journal_replay.md) describes all 130
distinct recovery relations and the additional 50 fault-injected builder scenarios.

Journal liveness adds weak fairness of progress. With finite batches, at most two
interruptions, and successful future I/O, the final viewer and checkpoint are
eventually published. It does not require the environment to generate further data or
eventually rotate logs. New source generations arrive only after the preceding modeled
publication completes; publication history overwritten before any journal is written
is outside the exactly-once claim.

### Geography and cache publication

`GeographyPublication.tla` maps to `fires.reuse.validated_signature`,
`fires.reuse.generation_matches`, `fires.reuse.write_layers`,
`fires.files.write_history_of_full_geography`, and
`fires.differential.write_history_of_differential_geography`. Each GeoPackage and its
metadata publish in separate steps. Full and differential outputs also publish
separately. The differential generation includes the authenticated full-history
checksum.

The safety and liveness configurations cover two target generations, at most two
interruptions, and both unconditional choices. Their 512 initial states combine
generation-0/1 bytes and signatures, valid/invalid versions, and complete/incomplete
layer declarations. This exercises matching caches, stale caches, and bytes that no
longer match same-generation metadata. Each graph has 4,286 states. Properties require
authenticated reuse, bypass when forced, rejection of mismatched checksums, and a
matching pair when the geography stage is acknowledged. Liveness adds weak fairness of
progress and requires eventual final-generation publication.

Generation tokens stand for collision-free content/dependency identities and complete,
successfully classified histories. Missing or malformed signatures behave like invalid
metadata at lookup. Computing derivation keys, complete classification, row selection,
geometry correctness, and GDAL serialization are not proved here. The model assumes
the writer produces the intended complete file and corresponding metadata; it checks
the publication ordering and subsequent reuse decisions. No other writer modifies
these files during a modeled run.

### Live external sources

`ExternalRefresh.tla` maps to `sources.external_sources.query_arcgis_source` and
`fetch_arcgis_source`. Two refreshes and at most one interruption cover evacuation and
other ArcGIS sources, missing/empty/two distinct feature snapshots, and failed/empty/two
distinct query results. The graph has 890 states. Query, digest comparison, temporary
write, replacement, and cleanup remain separate steps. A write failure before
replacement is distinct from a failed retrieval.

Properties check that failed retrieval retains an existing snapshot, raises when none
exists, and never replaces bytes; only evacuation responses can publish empty data;
equal feature digests cause no replacement; and interrupted unpublished writes preserve
the old version. A completed replacement changes the entire snapshot. A crash can leave
a temporary file; it never makes that file authoritative. Snapshot tokens represent
normalized feature digests, so timestamp rounding, geometry conversion, and digest
construction are assumed correct. Static downloads, buildings conversion, temporary-file
cleanup failures after publication, and concurrent writers are outside this model.

## Fetch recovery

`FetchCrash.tla` maps to ungated `pipeline.run_fetch_stage`, the scheduled-full marker
in `fetch_fire_sources`, and `pipeline_state` persistence. Both safety and liveness
configurations explore 13,594 states, starting from all 32 valid pending-stage/force
combinations, changed or unchanged fire and evacuation inputs, scheduled-full or
incremental collection, and explicit user forcing. At most two abrupt interruptions
can occur, including immediately after either independently durable source mutation.

The coordinator captures the previous marker and records every derived stage before
preparing boundaries or fetching inputs. This temporary requirement preserves the
previous unconditional flag. Scheduled full collection separately records its forced
rebuild. Only a completely successful, unchanged incremental fetch restores the exact
previous marker. A retry captures the surviving marker as its own prior state, so an
unchanged retry cannot relinquish work required before the interruption.

`MutationProtected` requires every derived stage whenever persisted sources differ from
the output, including the states immediately after snapshot and evacuation writes.
`LostRebuildIsImpossible` retains the stronger terminal guarantee previously violated by
the unmarked snapshot window. Other invariants check exact restoration, scheduled-full
forcing, preservation of prior work and its force flag, and skipped no-change runs.
TLC-exported completion records drive 512 real coordinator executions. A further 128
exported mutation-boundary records drive actual state persistence, abrupt process loss,
and truthful unchanged retries for both input families.

`FetchCrashLiveness.cfg` adds weak fairness of enabled progress and checks eventual
completion with output matching the stable input targets. The finite interruption budget
and continuing invocations are required progress assumptions. Retries use incremental
collection, demonstrating recovery even when the full-fetch checkpoint already advanced;
full-fetch due-time calculation has separate scheduling checks. Derived work is atomic
at this model's boundary: `RunScheduler` separately checks stage selection, ordering,
and acknowledgment. Gated publication retains its separate gate and checkpoint models.
Cooperating writer exclusion and atomic run-state replacement are required. Storage
power loss, new input revisions arriving during recovery, and writers bypassing the
run lock are outside this model.

## Explicit counterexamples

`GeographyPairExpected.cfg` starts with consistent old outputs and asks for
`PairAlwaysMatches`. It fails immediately after publishing new full-history bytes while
the differential file still contains the old generation. This records the intended
scope of atomic publication: one file at a time. The passing configuration instead
checks that the pair matches when the geography stage is acknowledged. Supported
`read_derived_layers` consumers now authenticate matching generations under a shared
lock and refuse an interrupted pair, regardless of pending state. Raw file readers
bypassing that protocol can still observe intermediate physical files.

## Common fault model and maintenance

Each replacement or unlink is atomic for process interruption, and a completed
replacement remains visible after restart. Unpublished temporary files have no effect
on recovery. The models do not assert power-loss durability: the source writers use
temporary files and replacement without explicit file/directory `fsync`. Storage
corruption during a run, forged metadata, hash collisions, UUID collisions, unreliable
locking filesystems, and noncooperating writers are outside the checked guarantees.

Safety is checked for all paths inside the finite bounds, including failures at every
modeled boundary. Fairness appears only in liveness configurations. Terminal protocols
disable TLC's deadlock check because successful completion intentionally has no next
work; the liveness property still rejects nonterminal executions that cannot finish.
No symmetry reduction or state constraint removes intermediate states.

When source behavior changes, update the mapped actions, properties, and implementation
conformance cases together. Add a new action when a persistent write gains its own
failure boundary. Preserve counterexample traces as regression cases before repairing a
protocol. Increasing a bound explores a larger finite instance; it does not turn a TLC
result into a proof for arbitrary instances.

# Composed pipeline invocations

`PipelineComposition.tla` models `pipeline.run_selected_stages`,
`pipeline.run_pipeline_stage`, the two fetch coordinators, the pending marker in
`pipeline_state.py`, and the publication checkpoint associated with the current KMZ. It
composes the stage-order, fetch, and publication contracts across policy changes and
partial invocations. The model uses the actual `PipelineState` operators.

## Checked guarantees

Every source revision missing from a derived output remains protected by either the
corresponding pending stage or durable deferred-input intent. Selecting a later stage
cannot erase that protection. Explicit forcing reaches every selected stage; inherited
forcing reaches the still-required stages. Execution stays inside the selected range.

A checkpoint matching the current KMZ can acknowledge only inputs prepared by geography
for that KMZ. Completing a standalone KMZ from older geography cannot acknowledge newer
collected inputs. KMZ replacement, checkpoint commit, checkpoint invalidation, and stage
acknowledgment are separate transitions with interruption points between them.

The `deferred_inputs` file records possible unpublished inputs before gated collection
can mutate sources. Gated acceptance first requires every derived stage, then clears
this marker. A skipped gate clears it only when its validated checkpoint covers the
saved inventory. An ungated fetch transfers the marker to pending derived work before
collection and cannot restore an empty prior requirement after an unchanged fetch.
Partial invocations that omit fetch leave deferred intent intact. An interruption
between writing pending requirements and removing deferred intent leaves both forms of
protection; retry can conservatively repeat work.

An ordinary regression found the need for that marker: a below-threshold gated run saved
new inputs, then an ungated unchanged run skipped all derived work. The regression
failed before the fix and now also covers intervening gated and ungated KMZ-only runs,
which can respectively remove or invalidate the publication checkpoint. The separate
marker survives both cases without changing the `PendingRun` schema.

## Bounds and assumptions

The safety and liveness configurations explore **113,677 states**. They start with
matching generation-zero inputs and outputs, a valid checkpoint, and no pending work.
Two exploratory invocations choose among all 15 contiguous ranges over fetch, geography,
score, KMZ, and reports; both publication modes; and both explicit forcing choices. One
new source generation can arrive, and at most one process interruption occurs. The third
invocation selects the complete ungated pipeline with stable sources and no further
failure. There are 506 distinct durable invocation-start states, including inherited
forced requirements, deferred changes, stale geography, and invalid checkpoints.
Threshold outcomes vary only for gated ranges containing fetch, where they affect
behavior; their duplicate values for other ranges are omitted.

Safety includes intermediate persistent states. Failure boundaries are before a stage,
before consuming deferred intent, before and after source replacement, before and after
checkpoint commit, and before stage acknowledgment. The liveness configuration adds weak
fairness of ordinary progress. With the final healthy complete invocation, all derived
artifacts eventually match the saved inputs and pending/deferred work becomes empty.
Arbitrary repeated partial selections or failures are not assumed to recover. The final
ungated run need not create a publication checkpoint; a later gated invocation can
conservatively rebuild when that checkpoint is invalid.

One generation represents either input family at the coordinator boundary. Composition
uses incremental fetching. `FetchCrash` separately exhausts all 32 prior pending states,
full versus incremental collection, and independent fire and evacuation mutations.
`PublicationGate` and its Lean oracle separately cover timer, mapped area, source
history, and evacuation precedence. Here the real gate compares concrete source
inventories and areas for both threshold outcomes; the composition proof does not
establish geospatial measurement correctness or every cross-product with scheduled
full-fetch timing.

The model assumes one cooperating writer, stable inputs during derived execution, atomic
marker/checkpoint replacement, and distinguishable completed KMZ file identities. It
models process termination, not power-loss durability. Geography, scoring, and reports
are generation-level effects; their internal algorithms, geography-pair reader protocol,
update-journal replay, viewer refresh, locks, and product caches have separate checks.
The initial consistent generation does not model migration of source changes deferred
before this marker protocol was installed.

## Implementation connection

`test_pipeline_composition.py` exports the checked TLC graph and replays all **19,240**
distinct invocation outcomes in **48 pytest batches**. The shared graph is generated
and checked once within the current pytest run; workers decode it once each. Every
history stays within one batch, retaining all **38,143** logical invocations. These
outcomes comprise 7,328 complete calls and 11,912 interrupted calls across all seven
failure boundaries. Coverage assertions check each boundary's count, all ranges, both
modes and forcing choices, deferred stale inputs, and inherited forced requirements.
Expectations come from TLC's reached terminal state rather than a second Python
implementation of the protocol.

Each root begins at the unique consistent initial state in an isolated directory. Exact
common prefixes execute once; each child continues from an independent, timestamp-preserving
copy of the actual files and the full surviving matcher state. This shares only identical
complete histories, never merely equal durable projections or final invocation choices.
The tree contains **19,240** concrete invocations. Regressions compare fresh full-history
execution with shared-prefix execution, including files, KMZ identities, and hidden TLC
path choices, and verify parent/sibling isolation. The Lean `ReplayPrefixes` proofs
establish sequential composition and failure preservation under explicit deterministic
transition and exact-copy assumptions. These proofs do not verify Python or file copying.

Every invocation calls the actual `run_selected_stages` and `run_pipeline_stage`. A matcher
preserves the full compatible TLC path through every actual artifact, marker, and
checkpoint observation; crashes and parameterized invocation choices consume explicit
edges. See the [execution extension](../execution_paths_extensions.md) for projection
details. It retains real pending and deferred marker I/O, real publication decisions,
checkpoint serialization and identity validation, and separately written source,
geography, score, KMZ, and report revision files. It compares all resulting revisions,
remaining requirements, marker presence, checkpoint contents and validity, selected
calls, and effective force flags with TLC. Process-loss injection uses `BaseException`
to bypass ordinary recovery handlers. Every watched file mutation reads a fresh complete
snapshot; adjacent control-only checks reuse the immediately preceding observation.

Expensive geography, remote fetching, index preparation, presentation generation,
logging, and product-cache setup are substituted at their dependency boundaries. The KMZ
substitute writes a real file and calls the real publication commit with the
coordinator's frozen inputs. Journal behavior inside the complete builder is covered by
[journal replay](journal_replay.md). This is finite conformance evidence for the modeled
coordinator executions, not a proof that arbitrary Python execution refines TLA+.

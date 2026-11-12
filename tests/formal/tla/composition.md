# Composed pipeline invocations

Recovery requirements have to survive across runs, including runs that select only part
of the pipeline or change the publication policy. A run that skips geography cannot
erase the need to process source data collected by an earlier run.

`PipelineComposition.tla` models `pipeline.run_selected_stages`,
`pipeline.run_pipeline_stage`, the two fetch coordinators, the pending marker in
`pipeline_state.py`, and the publication checkpoint associated with the current KMZ. It
checks the stage-order, fetch, and publication contracts together across policy changes
and partial invocations. The model uses the actual `PipelineState` operators.

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

TLC explores **113,677 states**. It starts with
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
checkpoint commit, and before stage acknowledgment. TLC checks these invariants over the
complete reachable graph. With the final healthy complete invocation and weak fairness
of ordinary progress, all derived artifacts eventually match the saved inputs and
pending and deferred work become empty.
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

## Liveness proof

TLC checks three premises of the Lean [rank proof](../lean/PeriScribe/RankedLiveness.lean)
on the same complete graph. The rank is a natural number in each reachable state, every
nonstuttering transition decreases it, and every state before the final invocation ends
enables a nonstuttering `Progress` transition. Under `LiveSpec`, weak fairness forces a
progress transition from any suffix that never reaches the final state. The rank cannot
decrease indefinitely, so that final state is reached. `FinalRecovery` checks its durable
contents. `EventuallyRecovered` records this temporal claim.

The rank leaves 64 positions per invocation. Within an invocation, later stages advance
by ten positions. Internal positions follow the effect order. For example, ungated fetch
consumes deferred intent before writing source data, while gated fetch does so after
deciding to proceed. A crash moves to the completed invocation position, and the next
invocation takes a new block of positions. The bound on invocations keeps all ranks
nonnegative.

The assessment is `(1, 2, 2, 1, 1)`, totaling 7. The rank represents local stage order
with different fetch paths and a separate interruption exit. The Lean argument uses
well-foundedness and the existing fairness premise. Checking the rank adds constant work
per explicit transition and keeps the same state variables and successor relation. A
comparison with direct TLC liveness checking matched the complete labeled graph.

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

Only idle states enumerate invocation choices. Recovery admits one complete ungated
choice, and exploratory invocations enumerate only ranges and flags that can take a
`Begin` step. This prunes rejected candidates while retaining every reachable state and
labeled successor. The path matcher accepts implicit stuttering as an unchanged
observation.

Each root begins at the unique consistent initial state. Exact common prefixes execute
once. Each child receives a separate copy of the branch's file contents, identities, and
full surviving matcher state. This shares only identical complete histories. The tree
contains **19,240** coordinator invocations. Regressions compare fresh filesystem histories
with shared prefixes, including files, KMZ identities, and hidden TLC path choices, and
verify parent and sibling isolation. The Lean `ReplayPrefixes` proofs establish sequential
composition and failure preservation under explicit determinism and exact-copy assumptions.

Every invocation calls the actual `run_selected_stages` and `run_pipeline_stage`. A matcher
preserves the full compatible TLC path through every actual artifact, marker, and
checkpoint observation; crashes and parameterized invocation choices consume explicit
edges. See the [execution extension](../execution_paths_extensions.md) for projection
details. Production pending-state parsing, publication decisions, checkpoint serialization,
and identity validation run over a branch-local in-memory file image. The source, geography,
score, KMZ, and report fixtures retain separate revision files in that image. Replay compares
all revisions, remaining requirements, marker presence, checkpoint contents and validity,
selected calls, and effective force flags with TLC. Process-loss injection uses
`BaseException` to bypass ordinary recovery handlers. Every watched mutation reads a fresh
complete snapshot. Adjacent control-only checks reuse the preceding observation.

The physical checks derive distinct effect inputs from the same current-run histories.
They exercise the default filesystem adapter, verify exact bytes and stamps and check that
files outside the operation are preserved. They also check failures on both sides of a
mutation, parse real pending markers, and exercise real publication stamps. Each full
image keeps its own comparison. A [source-bound footprint](../../../docs/algorithms/verification-tooling.md#pipeline-file-effects)
lets images share a physical witness when their command has the same path, argument,
target presence and directory layout. Lean composes the one-step transfer with the
original reply-dependent continuation and preserves the ordered trace. The complete
physical matrix applies when the source, live bindings, proof build, or fixture falls
outside the certified domain. Real hard-process tests retain independent crash and
recovery processes and actual on-disk files.

The ordered comparator runs the original coordinator for each history in its selected
batch and retains all raw reads, writes, full observations, and failure boundaries.
Within the reviewed [ordered witness domain](../../../docs/algorithms/verification-tooling.md#pipeline-file-effects),
continuous native histories cover the exact reader and writer classes, observed fault
frames, and stage/force dispatch. Their original ancestors run on the real filesystem,
and their full tapes and terminal paths must match the memory replay. The existing
complete native comparator applies whenever the ordered proof or runtime binding is
unavailable.

Expensive geography, remote fetching, index preparation, presentation generation,
logging, and product-cache setup are substituted at their dependency boundaries. The KMZ
substitute writes a revision file and calls the real publication commit with the
coordinator's frozen inputs. Journal behavior inside the complete builder is covered by
[journal replay](journal_replay.md). This is finite conformance evidence for the modeled
coordinator executions, not a proof that arbitrary Python execution refines TLA+.

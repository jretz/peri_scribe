# Pipeline scheduling and publication decisions

## Contract and context

The pipeline executes a selected contiguous range of fetch, geography, score, KMZ and
reports while preserving all outstanding rebuild requirements. A publication gate may
collect inputs now and defer their derived outputs. These are distinct states: downloaded,
required for rebuilding, and acknowledged by a completed KMZ.

Inputs are a year directory, selected range, optional force/full-fetch policy, and optional
publication thresholds (area quantities and elapsed duration). Publication comparison
uses aware instants and a checkpoint whose file stamp matches the current KMZ. The gate
measures raw source geometry on the same basis as the displayed source mapping; incident
acreage is not an area-change trigger. Consumers are CLI invocation, recovery and monitor
status. Cooperating commands hold the year writer lock.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Pending work and deferred inputs survive partial invocations and policy changes. |
| Rule interaction | 3 | Stage prerequisites, forced work, source changes and publication evidence interact across commands. |
| Mathematical reasoning | 2 | Unit-aware signed area differences, relative threshold tolerance and alias-connected capture times determine publication. |
| Scale and representation | 2 | Cached measurements and frozen source inventories must remain distinct from publication baselines. |
| Failure and concurrency | 3 | Input mutation, marker writes, stage returns and acknowledgements can fail independently. |

**Total 12: complex.** Area policy directly affects published results, so its decision
precedence must stay explicit even if a future refactor reduces implementation size.

## Approach and invariants

Pending stages are the canonical ordered union of old and newly required stages. The
unconditional flag is sticky while any pending work remains. Only successful completion
of the first pending stage removes it; running a later selected stage cannot acknowledge
an omitted prerequisite. Invalid run-state markers conservatively require a full forced
rebuild. A lock loser changes no shared pipeline state.

![Recovery intent precedes mutation and survives partial execution](assets/pipeline-intent.svg)

*Each row is a durable state. An unchanged retry inherits the surviving requirements, so
it cannot erase work introduced before an earlier interruption.*

Ungated fetch first saves all derived requirements, then mutates sources. It restores the
exact prior marker only after a successful unchanged incremental fetch with no deferred
inputs and no scheduled full collection. Gated fetch first records `deferred_inputs`.
Acceptance installs derived requirements before removing deferred intent. Deferral retains
intent, except a confirmed no-unpublished-data decision can remove it. Required work,
explicit force, or a full fetch overrides a gate skip. Switching policy therefore cannot
silently forget collected inputs.

The gate applies this precedence:

| Condition, in order | Decision |
| --- | --- |
| No valid checkpoint for the current KMZ | Build. |
| Evacuations changed, then city-reference digest changed | Build. |
| A previously processed source file changed or disappeared | Build. |
| No additional source snapshots | Skip; elapsed time alone is insufficient. |
| Candidate identity ambiguous, or eligible mapping unmeasurable | Build to resolve uncertainty. |
| Largest absolute eligible area difference reaches threshold | Build, including shrinkage. |
| Pending snapshots and elapsed interval reached | Build. |
| Otherwise | Defer while retaining collected inputs. |

Candidates skip collapsed polygons, group through known identifiers, and select the latest
observation/serial/object-ID ordering. Older-than-baseline candidates are ignored before
checking uncertain area. Use `abs(current - baseline)` with unit conversion; threshold
comparison admits relative tolerance `1e-12`. A new included fire has zero baseline.
First-capture times propagate over connected `(identifier, shape)` aliases, taking the
minimum across the entire component so attribute republication cannot renew a geometry's
capture age. The traversal is ordinary connected-component search, not merely adjacent
pair comparison.

## Worked examples and boundaries

With a 100-acre published baseline, a 10-acre threshold, the timer still pending, and no
earlier mandatory-build condition, successive collections accumulate against that baseline:

1. Collect 104 acres: the difference is 4 acres, so defer and keep baseline 100.
2. Collect 108 acres: the difference is 8 acres, so defer and keep baseline 100.
3. Collect 112 acres: the difference is 12 acres, so build. Commit baseline 112 only
   after the complete KMZ is published.

The download cache advances at every collection; the publication baseline advances only
with publication.

Suppose geography, score, KMZ and reports are pending, but `--only kmz` succeeds. Geography
is still the first pending stage, so the marker remains unchanged. Claiming that a finished
KMZ cleared all pending work would allow stale geography to become accepted state.

If a source snapshot changes and fetch then crashes, all derived requirements already
exist. The retry's remote data can be unchanged; that fact does not prove derived outputs
match the saved sources. The retry captures the surviving requirements and preserves them.

With a 100-acre published mapping and a 10-acre threshold, 90 acres triggers just as
110 does. A 200-acre delayed observation older than the published mapping is excluded.
An ambiguous alias joining two published fires requires rebuilding, rather than arbitrarily
choosing either baseline. Ten quiet hours without any pending snapshots do not publish
merely because an hourly timer is due.

## Costs and limitations

Stage-set bookkeeping is constant-sized (four derived stages). For S source files, M raw
mappings, V distinct identifier/shape pairs and E alias links, collection is O(S) metadata
work plus reading/measuring changed snapshots; first-capture components cost O(V + E).
Candidate grouping is linear in mappings and their identifiers after sorting pending paths.
Published-source lookup scans a snapshot's mapping rows per derived perimeter, so worst
case is the sum of those per-row scans. Memory retains the collection's M measurements.
Actual stage geometry, scoring and rendering costs belong to their own notes.

Collection caches are disposable; publication checkpoints are valid only for their
recorded KMZ stamp. File size/mtime stamps assume no undetected external substitution.
Locks exclude cooperating writers, not arbitrary filesystem edits. Partial ranges may
leave prerequisites pending forever; eventual recovery needs future invocations selecting
necessary stages and an end to failures. Single-file replacement does not provide
cross-file atomicity or power-loss durability.

## Implementation and verification

Owners: [pipeline.py](../../src/peri_scribe/pipeline.py),
[pipeline_state.py](../../src/peri_scribe/pipeline_state.py),
[pipeline_stages.py](../../src/peri_scribe/pipeline_stages.py), and
[publication.py](../../src/peri_scribe/publication.py). Ordinary checks cover
[state](../../tests/tests/standard/peri_scribe/test_pipeline_state.py),
[fetch recovery](../../tests/tests/standard/peri_scribe/test_pipeline_fetch_recovery.py),
[composition](../../tests/tests/standard/peri_scribe/test_pipeline_composition.py), and
[publication decisions](../../tests/tests/standard/peri_scribe/test_publication.py).

The [TLA+ inventory](../../tests/formal/tla/README.md) maps RunState, RunScheduler,
PublicationGate and FetchCrash, naming finite bounds and fairness premises.
[Composed invocations](../../tests/formal/tla/composition.md) covers policy changes and
partial selections; [command readers](../../tests/formal/tla/command_readers.md) covers
standalone validation. [Publication conformance](../../tests/formal/conformance/test_publication.py)
and [pipeline composition conformance](../../tests/formal/conformance/test_pipeline_composition.py)
connect concrete behavior. Abstract integer area categories do not prove geodesic area
measurement; real geometry and unit boundaries retain ordinary tests.

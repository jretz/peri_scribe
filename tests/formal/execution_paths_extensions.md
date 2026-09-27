# Continuous pipeline, cache, and geography execution paths

These bridges extend the whole-prefix matcher described in [execution
assurance](execution_assurance.md). They use initial nodes and directed edges from the
same successful TLC graph export. No restart or invocation may reset the matcher at an
arbitrary reachable node. Explicit events include both their action and resulting
observed value; terminal process-exit stutters require that value to remain unchanged.

| Area | Models | Concrete histories |
| --- | --- | ---: |
| Pipeline composition | `PipelineComposition` | 19,240 retained outcomes, each preceded by its actual earlier invocations |
| Parsed-cache synchronization | `ParsedCache` | 110 interrupted transactions with healthy retries, plus 12 uninterrupted configurations |
| Parsed-cache schema recovery | `ParsedCacheRebuild` | 18 initial prefixes and their actual repair |
| Geography readers | `GeographyReaders` | 162 original reader cases plus 20 writer-prefix/read histories |
| Geography publication | `GeographyPublication` | 44 publication/recovery histories, each followed by a later source generation |

## Pipeline composition

`helpers/pipeline_composition.py` exports all 113,677 checked nodes and recovers a
complete predecessor history for each of the 19,240 distinct terminal invocation
outcomes. Every history creates the consistent generation-zero initial files once. It
executes earlier invocations through the real coordinator, carries their files into the
selected invocation, and retains the same matcher throughout. The original assertions
for stage selection, force propagation, outputs, pending/deferred requirements,
publication payload, and checkpoint validity remain in place.

The projection reads separate source, geography, score, KMZ, and report artifacts; the
pending stage set and force bit; the deferred marker; and checkpoint content and KMZ
file identity. Real marker/checkpoint replacements, removals, and creation are observed
independently. A completed fixture stage produces one artifact observation. The source
fixture likewise observes its actual persisted effect, including unchanged fetches.

`Begin` is an explicit action carrying range, gate, force, source-change, and threshold
choices. It consumes the actual pending-marker change when the coordinator requires
work, or the unchanged observation when no initial marker is needed. `NextInvocation`
and process loss are explicit events. Internal stage progress cannot silently choose
another invocation, discard a crash allowance, or jump over a changed persistent
observation.

This strengthens the coordinator boundary, not the substituted remote retrieval or stage
algorithms. A completed generation artifact abstracts each fixture's internal write; it
does not prove that a production geography stage publishes both files atomically.

## Parsed-cache recovery

`helpers/cache_paths.py` observes committed SQLite state through a separate connection.
The projection retains table presence, receipt serials and checksums, every serialized
fire-row field, and every complex-membership field. Receipt file-stat hints are
excluded; the existing semantic checks retain authenticated read assertions.

Production SQL trace callbacks observe the preceding statement's completed effects.
Commit is consumed only after the actual commit completes. Interrupted transactions
close and roll back before the explicit `Abort` event; `Restart` occurs before the real
healthy `open_and_sync` retry. Because SQLite swallows callback exceptions, the observer
records and rethrows matcher failures after the operation. Transaction-internal writes
may be invisible to the observer, but they cannot publish partial committed records.

Schema resets expose separately committed table drops and creates. A real interruption
and connection close are followed by an explicit `CrashAndRestart`, then actual
`ensure_database_current` repair. The model now allows interruption before the first DDL
statement as well as after it. This adds two checked states, for 64 total. `ParsedCache`
adds a restart edge back to its existing write state; its 234-state bound is unchanged.
Neither change adds a production transition. All 288 prior pinned-reader schedules and
fallback assertions remain, but this extension does not claim whole-prefix matching for
that separate reader-scheduling model.

## Geography publication and readers

`helpers/geography_paths.py` builds three canonical real GeoPackage pairs. A model
revision denotes an exact checksum of those complete files. Later production staging
serializations copy the canonical bytes for the actual selected layer revision. This
avoids treating two byte-different GDAL outputs as one symbolic checksum. Before
copying, every selected layer is compared with its canonical complete frame, including
all values, geometry, and CRS. Layer selection, file replacement, metadata construction,
signature validation, real file reads, and cooperating filesystem locks remain
production operations. Geometry derivation and GDAL's serialization algorithm are
outside this protocol contract.

`helpers/geography_readers.py` preserves all 162 original authentication cases and adds
20 histories: initially absent or valid-old pairs, strict or tolerant readers, and each
of five completed writer prefixes. Every public bytes/signature replacement is observed
while the actual writer lock is held. An independent context fails to acquire a reader
lock during writing. After normal or interrupted writer release, the same path continues
through actual reader acquisition, authentication, each returned layer, and release. A
competing writer is rejected at every real layer-read boundary. Same-owner nested reads
remain covered by ordinary ownership tests; this finite model represents the independent
reader and writer.

`helpers/geography_publication.py` retains real full/differential generation reuse and
`run_selected_stages` acknowledgment. Twenty-four baseline histories cross forcing with
12 initial populations: old, reusable, mixed, stale checksum, wrong version, and missing
layer declarations. Twenty further histories interrupt an old pair before and after each
of full bytes, full signature, differential bytes, differential signature, and pending
acknowledgment, under both forcing policies. Recovery uses the exact surviving files and
matcher. Exit after completed acknowledgment is an unchanged terminal event. Every
history then records a second source generation and publishes it through the same
coordinator.

Raw signature checksum, dependency generation, version validity, and layer completeness
stay distinct from actual file identity and pending state. Explicit source-generation
changes include their actual marker effect. Reuse semantic assertions additionally
verify that a complete reusable pair performs only acknowledgment, while forcing
performs every public replacement. The separate physical-pair counterexample remains
valid: refusal protects readers during interruption; no cross-file atomic rename is
assumed.

## Adversarial checks and limits

The shared matcher tests now require an explicit action to agree with its observed
mutation and prohibit changed projections from using a terminal-stutter exception. A
publication-specific negative control attempts to publish a new signature before its
bytes. That entire projection is individually reachable in the model, but the matcher
rejects it after the observed old-pair prefix.

These are finite execution-conformance checks with reviewed projections and dependency
substitutions. They do not prove unbounded Python refinement, arbitrary thread
schedules, foreign writers, power-loss durability, hash collision resistance, or
filesystem and SQLite internals. Exceptions model the added publication faults; the
separate hard-crash suite supplies real interpreter termination for its documented
protocols.

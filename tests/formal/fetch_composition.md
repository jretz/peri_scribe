# Fetch component composition

The feed coordinator has two independent input groups. Feed kinds and the full-fetch
flag determine the worker wave. Prior recovery work, index failure and deferred indexing
determine what the caller does after that wave has joined. Testing those groups through
one exhaustive Cartesian product repeats native worker startup and the same marker
storage implementation.

The conformance check keeps all 2,000 policy tuples. Every tuple calls the real
`pipeline.run_fetch_stage`, `fetch_control.collect_fire_sources`, `fetch_all_feeds` and
`summarize_feed_outcomes`. It checks the exact recovery marker before collection, the
actual worker callback and its base directory, year and full-fetch arguments, index
ordering, successful cadence acknowledgment and the original six final observations.
Only the joined collection input and the marker storage boundary are factored.

## Independent model boundary

The complete `FeedCoordinator` model retains its bounds, actions, safety properties and
liveness checks. Its `index` states are successful collection cuts. Its `failed` states
with a fatal worker result are failed collection cuts. For every input tuple, the test
extracts the cut's saved snapshot set, fatal status and ordinary source-error status.
Fatal collection prevents every later success phase, so source-error status is irrelevant
in that branch; `FetchComposition.fatal_ignores_source_error` proves this projection.

The test checks exact equality of the complete cut sets across all eight combinations
of prior work, index failure and deferred indexing. It then evaluates every cut with the
compiled `FetchComposition.execute` definition and requires equality with the complete
TLC terminal outcome set for each of the 2,000 tuples. This is a relation comparison,
including every permitted cancellation outcome. Python does not implement an alternate
expected policy. Lean also proves that the ordered index, acknowledge and restore phases
equal the closed projection for every natural-number snapshot mask and every policy.

## Native collection and storage witnesses

For each of the 250 full-fetch and feed-kind combinations, `NativeProbe` runs the real
`asyncio.run`, `TaskGroup`, semaphore and thread executor through the full production
facade. The native checks retain joined-worker, concurrency-bound, actual saved-file,
index, marker and acknowledgment observations. The returned feed-order values and
exception tree are captured after the actual runner has shut down. Saved source bytes
are independently read. The captured collection must belong to its complete TLC cut
set, and the native facade outcome must belong to its TLC terminal set.

Captured values are frozen tuples and dataclasses shared only during the current
conformance call. Paths are stored relative to their private year directory and
relocated for each policy invocation. Exceptions are stored as immutable type-specific
message trees; each invocation receives a fresh exception and traceback. No successful
test result, process, mutable filesystem tree or prior-run receipt is reused.

The 2,000 policy invocations retain independent marker byte images. They run the actual
production JSON codec and marker functions over the existing pipeline `File` port.
The port's existing source/runtime qualification and Lean file-footprint certificate
must succeed before this lane is used. Unknown adapter source, replaced executable
bindings, changed native primitives or stale proof artifacts select the original full
2,000-case native replay. Marker codec and atomic fault checks, native process-loss
tests and the complete pipeline file-effect matrix remain independent owners of the
storage boundary. The 250 native waves also use the real marker and cadence storage.

Another 42 native facade invocations cover every later policy combination for unchanged
inputs, successful changed inputs, and an ordinary source failure with a successful
sibling. They retain native prior-marker, deferred-marker, failed-index and successful
cadence interactions at each distinct post-collection branch.

The absent cadence input used by every original coordinator case is supplied to the
policy lane at its read boundary. The real cadence policy still selects full collection.
The acknowledgment delegate checks the actual path and aware UTC timestamp, successful
collection, absence of source errors and successful index before recording the call.
Native cadence serialization, read failures and publication failures retain their
ordinary, property and native coordinator owners.

The binding also qualifies the collector, concurrency cleanup helpers, controlled worker
fixture, marker byte backend and cadence codec by their normalized source and loaded
compiled functions. Relevant library objects and mutable namespace tables must retain
their reviewed identities and values. Changed source, executable substitution, a changed
namespace or unavailable current proof selects the complete native replay. Focused
negative tests exercise that fallback through actual native marker writes and reject
collection before exact recovery intent for both empty and preexisting prior work.

All 32 forced sibling-cancellation cases still execute their original native paths.
They require a genuine cancelled task to coexist with a completed late filesystem write.
Hard-process tests retain fresh execution and their original interruption boundaries.
Uncontrolled repetitions of an identical worker input are replaced by the checked
independence relation; forced schedule and operating-system witnesses are retained.

## State and fetch wrapper basis

All 1,248 `RunState` records still invoke the actual state wrappers. Native persistence
retains all 32 codec round trips, all 32 malformed-state records, all 160 completion
records, and both empty-unforced and full-forced requirements from each of the 32 input
states: 288 native records. The other 960 requirements use independent byte images and
the real codec. Their actual effects must include exactly the initial state write and
the required replacement, even when the resulting bytes are unchanged. The entire
require and completion relations continue to be compared with the independent TLC and
compiled Lean definitions. Unsupported qualification restores all 1,248 native records.

All 512 `FetchCrash` completion tuples still invoke the actual fetch facade. Each retains
its real independently created source revisions and cadence files. Marker storage alone
uses the qualified byte port for 420 tuples. The 92 native marker witnesses cover all
prior states for unchanged incremental collection and every policy tuple from empty or
fully required prior states, with both force flags. The compiled `finishFetch` projection
must match every TLC completion before this lane is used. All 128 source-interruption
and unchanged-retry cases remain fully native. Unsupported qualification restores all
512 complete native invocations.

## Cost and limits

Let `W` be the number of distinct full-fetch and kind inputs, `P` the number of complete
policy tuples and `C` the number of distinct model cuts. Native concurrency work is
`O(W)` instead of `O(P)`. Actual policy execution remains `O(P)`. Model projection and
compiled-oracle comparisons are `O(C)` and retain their complete finite input sets.
Immutable receipts occupy `O(W)` result data; each policy invocation has a private
constant-size marker image. The proof establishes the component relation, while native
witnesses establish correspondence at the declared I/O and concurrency boundaries.
It does not replace hard-process, scheduler cancellation, codec or atomic-write tests.

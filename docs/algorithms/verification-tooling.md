# Verification evidence and execution

The verification tools share expensive work, but each result must still describe the
complete history that was checked. Process ownership keeps cleanup attached to the work
that created it. Temporary evidence sessions, replay of shared history prefixes, and
coverage receipts keep incomplete or unrelated results from counting as success.

## Contract and assessment

Inputs are registered model configurations, checked graphs, executable implementations,
test inventories, and source identities. Outputs are checked evidence and explicit
success/failure results for one invocation. The [formal guide](../formal_verification.md)
and [testing guide](../testing.md) own invocation commands and verification policy.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Replay retains full compatible paths and exact preceding executions. |
| Rule interaction | 3 | Sharing must preserve case ownership, hidden model choices, and independent branches. |
| Mathematical reasoning | 2 | Graph traversal, typed projections, prefix trees, and batching compose. |
| Scale and representation | 3 | Shared graphs and prefix execution make the complete checked corpus practical. |
| Failure and concurrency | 3 | Worker cancellation, producer locks, and fresh evidence receipts span processes. |

Total **13: complex**. Model-specific oracles and test factories inherit the domain
contracts they exercise; they do not introduce a second authoritative policy.

## Process and evidence ownership

Each outer proof job owns its processes through cleanup:

1. Shield launch so cancellation still acquires any process handle created during
   admission.
2. Run in a private POSIX session/process group. Nested tools retain the outer job's
   group.
3. On timeout or cancellation, complete admission, kill the whole group, and drain output
   before propagating the original failure. Repeated cancellation cannot abandon cleanup.

A nested tool cannot leave descendants running after its caller exits.
Deliberately detached descendants are outside the adapter contract.

On macOS, a second signal can find a group whose members have exited but are still
awaiting reaping. The adapter retries `EPERM` briefly so that this state can settle.
It finishes when signaling succeeds or the group disappears, and propagates a denial
that outlasts the retry window. [XNU group signaling]

[XNU group signaling]: https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c#L1605-L1622

TLC configurations run through a bounded semaphore, each with private temporary
and model metadata directories. Reusable conformance evidence requires successful
checking and validated decoding. Checks without an evidence export validate
their registered outcome from exit status and output: ordinary success or the exact
expected counterexample. Tool failure, timeout, malformed output, or an unexpected
invariant failure does not satisfy that contract.

The three formal Node adapters for refresh, response monitoring and update-viewer
checks use `--single-threaded`. V8 performs compilation and garbage collection without
background tasks; the original scripts still execute every input trace, callback and
assertion. Async file reads, promises and timers retain their existing behavior. This
setting leaves the real Chromium and viewer QA tasks unchanged. It does not limit all
Node or libuv threads and is not an operating-system CPU cap.

The option is verified against the locked Node executable and its
[V8 flag definition](https://github.com/nodejs/node/blob/v26.13.0/deps/v8/src/flags/flag-definitions.h#L3694-L3719).
The definition applies to both macOS and Linux architectures; Linux execution remains
unqualified locally. A Node upgrade requires checking the flag's availability and
repeating native input/output parity and aggregate resource measurements.

Both TLC launch paths use HotSpot's first compilation tier. Each finite request has
fresh TLC classes, so optimizing the same methods again consumes substantial CPU.
On the selected toolchain, the complete 57-model comparison used about 18.3 CPU seconds
with this setting and 26.2 with higher tiers enabled. Every model count matched, as did
all 45 exported graph and state receipts. The graph comparison renamed only opaque
fingerprint IDs to their actual discovery ordinals; it preserved all raw fields and
values, initial marks, action labels, duplicate edges, and successor order. This changes
compilation policy while retaining the original TLC arguments and model limits.

The formal gate compiles its worker once in the fresh evidence session. An admitted
model leases one JVM and sends one request. The worker loads the locked TLC archive
through a new classloader, runs the model in its own thread group, and writes diagnostics
to that request's private directory. It closes the classloader and checks for remaining
model threads before returning the matching completion receipt. The parent still checks
the status and diagnostics and validates each export before publishing evidence.
The JVM's compiler, runtime services, and heap survive between requests. TLC classes,
model state, and temporary files belong to one request.

For example, after the first model returns, the next model in that slot can start in the
warm JVM with fresh TLC classes and files. A timeout kills and reaps the process group
while it still belongs to the failed request. The next model in that slot starts a fresh
worker. Idle workers exit when the controller closes their request streams. A hung
shutdown also triggers forced cleanup. At most one model can be affected by a worker's
failure, and a failed request cannot supply evidence. For `N` models and `K`
admitted slots, at most `K` JVMs stay live for `N` independent checks. Each JVM has a
1 GiB heap limit. The adapter scores `(2, 2, 1, 2, 3)`, totaling 10. Requests and replies
must match in order, argument lengths preserve exact UTF-8 boundaries, and process
ownership must survive cancellation. Tests exercise completion, an expected failure,
and cancellation while another worker continues. A comparison across 62 checks,
including repeats and the known counterexample, matched 49 raw graph exports and saved
about 20 CPU seconds.

A check already owned by an enclosing process group uses the direct Java launcher, so
its parent can still terminate the entire job. Both execution paths run the same TLC
engine and validate fresh results through the current evidence session.

When safety and liveness use the same initial states and next-state relation, one TLC
configuration can check both on the same explored graph. This applies to static
download, document publication, log rotation, browser refresh, snapshot publication,
monitor context, ordered workers, building construction, fetch recovery, durable update
validation, and worker lifetime. Each combined configuration uses the original fairness
assumptions and retains every invariant and temporal property. TLC checks state and
action safety throughout exploration, then checks liveness under fairness.
Comparisons at a fixed fingerprint polynomial matched the exploration counts and
serialized conformance graphs byte for byte. For the last five protocols, two runs in
opposite orders saved about 1.9 CPU seconds in total. The raw graph exports matched
after omitting implicit dashed stutters and DOT layout directives.

### Fresh conformance admission

The full gate keeps four native ordinary Python sessions alongside one proof job. That
job checks every model, builds Lean, and runs every registered pristine mutation target.
The complete ordinary and QA graph and the proof job must both exit successfully before
one stock five-worker conformance pool starts. The independent known-counterexample
check follows successful conformance.

For example, proofs may finish while browser checks are still running. Conformance waits
for the browser and every other ordinary check. If either prerequisite owner fails, its
sibling is cancelled and joined; no formal worker starts. A later formal failure fails
the whole invocation after its native process group has closed.

The [coordinator](../../tests/formal/helpers/overlap.py) owns these boundaries:

1. Hash the complete source, test, configuration and lock inputs once. Check file
   membership and generations at phase boundaries and before conformance.
2. Run ordinary checks and proofs concurrently. The ordinary runner validates its native
   collections, complete protocols and coverage before it reports success. The proof
   owner requires every positive model, the actual Lean build and the exact pristine
   target inventory. The live corpus owner remains available through all consumers.
3. Join both owners and require success before starting the complete formal worker pool.
   Stock pytest-xdist owns collection agreement, work stealing and worker lifetimes.
4. Keep every native collection and setup, call and teardown report through a [report
   observer](../../tests/formal/helpers/conformance.py). Require identical complete
   collections from all five workers and exactly one passing protocol for each item.
5. Join all positive graphs before running the independent known-counterexample check.
   Preserve the closed reports beside the ordinary command's explicitly reported
   coverage session. Its session marker must agree with that directory.

The observer changes no scheduling decisions or worker factories. Native numerical
libraries use one thread per worker. Explicit parallel conformance cases retain their
own worker counts and resource checks. The five-worker setting leaves room for
controllers and native work; it is not an operating-system CPU quota.

The ordinary and formal controllers receive SIGINT with up to ten seconds for their
existing cleanup handlers. The process adapter drains output, terminates remaining owned
processes, and requires physical group absence before returning. Repeated cancellation
cannot abandon this wait. Detached descendants and arbitrary hard death of the
coordinating parent remain outside this cooperative cleanup contract. These Python and
POSIX process-group facilities are available on macOS and Linux; retained performance
measurements come from macOS.

[VerificationAdmission](../../tests/formal/tla/VerificationAdmission.tla) was checked
before implementation. Its finite bound has four ordinary lanes, one sequential proof
job, one QA phase and one five-worker formal phase. It checks prerequisite ordering,
nominal capacity, complete positive success and no admission after abort. The reduced
model checked 74 distinct states from 135 generated states. Native exit, complete
collection, exact protocol completion and physical cleanup remain concrete conformance
obligations, rather than consequences of the finite state count.

The coordination algorithm scores **2/1/0/1/3 = 7, complex**. Completion order
determines when the final phase can begin; its prerequisites form a fixed conjunction;
the worker set bounds in-memory state; cancellation spans independently owned processes.
For `F` source inputs and `T` formal items, input validation uses O(F) metadata and
native scheduling and report evidence use O(T) state. Source bytes are hashed once per
invocation; phase checks scan metadata. Each ordinary and formal worker owns its
interpreter and mutable test data. No prior verdict supplies current-run success.

An invocation owns temporary corpus storage with a live lock lease and an identity
covering specifications, configurations, adapters, and checker inputs. A producer lock
admits one producer for each declared export. Completed evidence is published from private
staging; consumers reject expired or incompatible sessions. Each worker decodes its own
containers. Top-level runs start fresh sessions instead of reusing a previous run's
successful files.

The model registry declares which consumers need directed graphs and which need only
reachable state values. Both modes run the complete TLC exploration with the same
properties, bounds, and fairness conditions. The graph export retains each initial
mark and explicit labeled edge. The text export retains every distinct state in discovery
order. The text writer emits a second copy of each state for implicit liveness stutters.
The decoder requires consecutive record numbers, the exact distinct count, and the
expected number of copies of every raw label. For example, when the writer emits
`A, B, A, B` with two distinct states and temporal checking, the receipt retains `A, B`.
With the same diagnostics, `A, B, A, A` fails the multiplicity check.

Typed graph and state receipts have separate keys. A graph request for a state-only
configuration fails before lookup or generation. State consumers can project a complete
graph when another consumer needs its edges. For `S` emitted states and `B` bytes of
text, state decoding visits the text once and retains the raw values and `O(S)` record
metadata. The adapter scores `(2, 1, 1, 2, 2)`, totaling 8. Record order, exact values,
and evidence publication remain part of the existing checked-corpus contract. At a fixed
fingerprint polynomial, a warmed comparison of 24 configurations matched every ordered
raw field, exploration count, and temporal check. The export, decode, and one receipt
write and read used about 3.9 fewer CPU seconds.

### Immutable TLC action frames

The reviewed finite configurations can share immutable field values during exploration.
The profiles include PipelineComposition, JournalReplay, FeedCoordinator, OrderedWorkers,
FetchCrash, BuildingsConstruction, and the liveness configurations for backward monitor
context, snapshot collection, and geography publication. A further 17 profiles cover
safety configurations. The checker asks TLC for the initial states, ordered actions,
and invariant predicates of the current model. It calls
the official evaluator on a representative for each distinct set of action inputs. The
resulting ordered patches contain the fields the action can change. Applying a patch to
another state retains that state's other fields. The graph keeps every concrete state,
initial mark, label, and edge occurrence, including repeated edges.

The checker determines an action's inputs from its resolved semantic tree. For
example, when one arm copies `x` and another writes `x`, the patch must carry `x`
because at least one arm writes it. The input key must then include the previous `x`
because the copying arm supplies it as a result. When a conjunct constrains `x'`
and another says `UNCHANGED x`, the previous `x` can determine whether the
conjunction has a successor. The input key includes it in this case too. A
[Lean proof][frame-proof] shows how equal ordered patches and the copy guarantee
preserve the full ordered successor list and reachability.

In the safety profiles, each resolved action has its own input table. An action whose
context binds a scalar request number shares results only within that exact binding.
An unsupported context or dependency shape evaluates the original action on the
complete current row. This also handles primed reads that the projection analysis
cannot qualify. The checker evaluates the original state invariants and boxed action
properties, and uses TLC's value formatter for the ordered raw evidence. If the
profile declines, standalone TLC checks the current sources and supplies the result.

The [Java checker][frame-checker] uses this path only for the reviewed source
closure, configurations, and TLC archive. It verifies the copy guarantee on
representative successors and retains every original invariant and action property.
For PipelineComposition and FeedCoordinator, a progress predicate is witnessed by
a nonstuttering edge in the exact progress action subset. The checker validates the
live predicate, stuttering tuple, and action subset before using that equivalence.
FeedCoordinator also checks the resolved quantified action bindings and the
intersection with the original next-state relation. Other progress predicates run
through TLC's evaluator. Unqualified inputs use standard TLC.

The checker can split a reviewed state predicate at built-in conjunction and
implication. It retains the original order and skips an implication's consequent
when its antecedent is false. TLC evaluates each leaf on one state per exact set
of leaf inputs. The checker also evaluates the actual rank expression on the
before and after fields. JournalReplay applies its comparison only when both
states belong to the original unreplaying publication subgraph.

The liveness profiles check their eventualities using the complete framed graph.
The checker resolves every weak-fair clause to actual TLC actions and their bound
parameters. It checks the full stuttering tuple and evaluates the actual goal predicate.
Topological order supplies a decreasing rank for every nonstuttering edge. Each
reachable state outside the goal must have a nonstuttering edge admitted by at least one
of the declared fair clauses. A FetchCrash state can have a Crash successor. It still
needs a successor from the separately declared weak-fair Progress relation.

An infinite behavior that avoids the goal must eventually stop taking nonstuttering
edges, since each such edge decreases a finite rank. At its final state an enabled
fair action stays enabled throughout that suffix. Weak fairness then requires progress,
contradicting the stuttering suffix. The [ranked fairness theorem][ranked-fairness]
covers the individually declared clauses. The checker still evaluates each action
property on its exact before and after input values and retains every edge occurrence.
An unsupported fairness clause, missing progress witness, or nonstuttering cycle sends
the configuration to standard TLC.

The [receipt decoder][frame-receipt] validates the complete versioned inventory before
publication. For graphs, it checks every endpoint and action code and requires a
strictly earlier predecessor for each noninitial row. This proves reachability in
discovery order. The frame path also respects state-only registrations and keeps
count-only evidence private when no consumer needs an export. Workers restore raw
TLC values from immutable field tables with 16-bit ordinals. Each field admits at
most 65,535 distinct values. Feed outcomes and journal recovery checks
select matching state rows in order before decoding their observed fields. The
processed pipeline receipt shares repeated ordered field rows and action names.
Workers restore independent mutable lookup maps before replay. Let `V` be the number of
states, `E` the number of edge occurrences, `F` the number of fields, and `K` the number
of distinct action input keys. The graph and action cache use `O(VF + E + KF + P)` space,
with `P` the total size of
cached patches. Exploration visits each of the `V` states, evaluates at most `K`
full action applications, and lifts each of the `E` edge occurrences. The
optimization scores `(2, 3, 3, 3, 2)`, totaling 13. Exact dependency and copy
rules, the shared representation, and atomic publication determine which runs can
use the compact graph.

The ranked eventuality check adds `O(V + E)` time and `O(V)` space. It scores
`(2, 2, 3, 2, 2)`, totaling 11, for reasoning about behavior over time, the interaction
of fairness with the goal, the rank argument, the complete graph, and failure before
publishing a receipt. A warmed comparison matched all reachable states, initial marks,
implicit stutters, and ordered explicit edge occurrences against stock TLC. The two
registered checks and graph receipts took about 1.37 CPU seconds, down from 6.07.

[frame-proof]: ../../tests/formal/lean/PeriScribe/FrameLifting.lean
[ranked-fairness]: ../../tests/formal/lean/PeriScribe/RankedLiveness.lean
[frame-checker]: ../../tests/formal/tla/FrameChecker.java
[frame-receipt]: ../../tests/formal/helpers/tlc_frame_wire.py

## Full paths and shared prefixes

![Shared execution prefixes branch into independent copies](assets/verification-prefixes.svg)

*Copies of A’s durable state separate into B’s and C’s private directories. B then
changes its own files and advances its full matcher; neither A nor C changes. The
always-visible branch diagrams preserve both the equal starting states and B’s changed
result without motion. A and B label schematic file contents, not literal filenames.
The two moving copies explain isolation, not concurrent scheduling: concrete replay
can create and visit the branches in turn. The loop reset is a visual replay.*

Each branch starts from its own copy of the shared prefix's durable state. Siblings
never share mutable durable files, so work on one continuation cannot affect another.

The filesystem witnesses copy the completed parent tree into each child's private
directory with file metadata preserved. For example, each copy of a KMZ retains the
parent's nanosecond timestamp so an otherwise valid publication remains valid in that
branch.

Conformance checks the transitions in a complete execution. It retains every compatible
full model state, including paths with internal steps or stuttering steps that leave the
observed state unchanged. A state can be reachable on its own even when the observed
order is impossible, so checking states independently is insufficient. Typed graph
projection retains exact node identities and successor order.

The authentication checks replay the maximal histories of their shortest-prefix
inventory. Each edge is identified by its source and position in that node's outgoing
list. Even equal parallel edges have separate positions. Breadth-first discovery
records one shortest path to each state. For every edge, extend its source's path by
that edge. A history that is also a strict prefix of another history can use the
longer replay's observations. For example, if the inventory contains `[A, B]` and
`[A, B, C]`, the latter checks A and B in order with the same initial file contents
and scope state. Each removed history extends to a retained one because the finite
extensions strictly increase in length. The selection checks that every exported
occurrence is covered.

Each concrete history opens its own real scope and checks that closure restores the
prior context, deactivates the owner, and clears both evidence maps. Every active
sequential prefix has an explicit End edge that closes that exact owner. The parallel
model closes published and aborted owners on its Cleanup edges. Earlier parallel
prefixes have empty maps. The retained histories include real closes for both active
and expired owners with empty maps. The full and maximal replays produced the same
cleanup inputs in the finite models, including checksums and whether evidence matched
the current file identity.

The selection scores `(2, 1, 1, 1, 1)`, totaling 6. It uses ordered paths, one
prefix rule, breadth-first discovery, finite path storage, and a real scope
finalizer. With V states, E edge occurrences and maximum path length D, it uses
O((V + E) × D) time and storage. Separate production tests cover concurrent cleanup.

Each durable observation rereads every source and output value, marker, and checkpoint
from the current branch. The replay keeps the paths for one invocation and freezes the
UTC clock at the fixture instant. Existing observation regressions alter unrelated files
before each observed mutation to check that the snapshot includes those changes.

Build a prefix tree from complete invocation histories. Identical complete prefixes
execute once. Each continuation receives a private copy of the durable bytes and file
identities plus the full surviving model matcher. Terminal nodes still record a requested
history even when they have children. Weight each subtree by its invocation count and
greedily assign whole roots, heaviest first, to the least-loaded batch. This balances work
without splitting a shared prefix between workers.

For histories `[A, B]` and `[A, C]`, execute A once, copy its durable output independently
for B and C, and retain both complete outcomes. Reusing the same mutable directory lets
B contaminate C. Restarting the abstract matcher from A's visible projection can also
lose hidden choices needed to reject an impossible continuation.

Pipeline composition replays the full tree over an in-memory file image with independently
copied branch state. The virtual year shares lexical path joins across those branches. The
same coordinator parses and writes pending markers, evaluates publication, and checks the
saved KMZ identity. The physical lane derives its inputs from the current tree's effects
and checks the local adapter's raw data, result or exception, and surrounding files.
Every raw read in the virtual replay sees the empty initial image, a recorded before- or
after-image, or a branch copy of one of those images. The maps flag changes within the
fixture's KMZ write, before control returns to a reader. The physical lane checks marker
bytes and absence, deferred-marker presence, and the canonical KMZ stamp in the real tree
on both sides of each successful effect. It reuses the same materialized files for those
reads and the effect check.
Failures before and after mutation distinguish whether the operation took effect. The
fault checks use one surrounding image per command and target input. The frame check
compares the files outside the target as well as the target. Full filesystem
histories and separate hard-process tests exercise the real sequence of effects,
including interruption and recovery across process lifetimes.

The [effect proof] requires one-step agreement on replies, observations, and resulting
state. This allows a later command to depend on an earlier read or failure. It separately
composes preservation of every key outside the trace's effect footprints. The adapter
assessment is `(2, 2, 1, 2, 3)`, totaling 10. Branches depend on prior writes, replies can
change later effects, raw byte and file identity relations connect the representations,
and interruption can leave a mutation applied. For `N` observed effects and `U` distinct
physical cases, the coordinator still runs all `N` effects and checks each resulting
projection. The physical lane applies each retained case once, plus the independent
whole-history and hard-process checks. Branch images have a fixed number of fixture
files. The physical comparison is finite evidence for the one-step assumptions.

The hard-process crash checks share a successful seed process within each family.
The seed chooses the initial files independently of the fault boundary and exit
method. For example, a builder seed publishes the first generation before either an
interruption at the next KMZ replacement or one at the next journal append. The
checked corpus publishes the seed directory after the seed exits successfully. Every
case copies the real files, their modification timestamps, and the seed observations
to private storage before starting its crash and recovery processes. The trace still
identifies three distinct process lifetimes. Each case observes its own hard
termination, cleanup markers, and recovery against the checked model.

For `C` cases across `F` families, this runs `F` seed interpreters, `2C` crash and
recovery interpreters, and copies each family's seed bytes once per case that uses
them. The adapter scores `(2, 1, 0, 1, 2)`, totaling 6. Replay depends on preserving
the seed trace and file identity, and publication uses the existing producer lock
and current-run lease. The [shared-prefix proof] applies to the exact copied state.
The [crash checks] and [retention checks] exercise the independent continuations and
verify real process outcomes.

[shared-prefix proof]: ../../tests/formal/lean/PeriScribe/ReplayPrefixes.lean
[effect proof]: ../../tests/formal/lean/PeriScribe/EffectRefinement.lean
[crash checks]: ../../tests/formal/conformance/test_process_crashes.py
[retention checks]: ../../tests/formal/conformance/test_product_retention.py

Log rotation replay checks all 162 histories by executing 18 first rotations and
copying each completed prefix for its nine second-rotation cases. Each continuation
inherits the entire compatible model path and an independent copy of the checksum
table and real files. Both the rotation recovery assertions and the final occurrence
checks still run. Each archive observation decodes and hashes the same bytes read
from disk. This uses the existing prefix proof and copying assumptions.

One TLC exploration supplies the complete update-publication graph and the journal
recovery observations. The [journal replay design](../../tests/formal/tla/journal_replay.md)
explains how the observer variables preserve the original graph and rank obligations.
The publication adapter visits the checked nodes and edges once and preserves the
order of each retained edge. The replay-only branch remains available to the recovery
checks through the same checked corpus.

The first builder worker validates the complete publication projection and
publishes immutable matcher evidence for each mode under the current corpus
lease. Later workers restore their own matchers from it. A matcher starts
among the mode's allowed initial states and can advance only to an allowed
state. For example, an edge from an allowed publication state into an
excluded recovery or publication-mode state cannot extend the path. This
restriction preserves the order and multiplicity of eligible edges and
retains the phase for terminal process exits. The complete graph remains
available for other checks. The corpus lock publishes the evidence only
after successful validation and encoding.

For `V` states and `E` edges in the complete checked graph, the producer
takes `O(V + E)` time and temporary space. The encoded evidence and each
restoration use `O(v + e)` time and space for the allowed states and edges.
This projection scores `(2, 1, 1, 2, 2)` for path history, mode selection,
induced edges, compact evidence, and publication under concurrent access.

The journal builder shares the first completed publication within each pair of prior
and current publication modes. Rotation cases also share the interruption immediately
after writing the second journal. Each of the 50 continuations gets independent files
and fixture maps, checks its copied KMZ identity, and retains the full matching path.

## Pure fixture reuse and oracle batching

Pure repeated inputs can share immutable results within the current check without
reusing verification evidence. Pipeline graph preprocessing memoizes durable-record
parsing by exact TLC record text. The parser cache belongs to one graph construction;
it retains no checked graph or success receipt. Frozen durable records include the
complete pending-stage tuple, so sharing a parsed value cannot merge model node IDs,
actions, predecessor histories, or hidden-state candidates. For `N` record references
of length `L`, the expensive parsing work runs for only `U` distinct records. Hashing
and comparing text still costs `O(N * L)` in the worst case; the cache retains `O(U * L)`
text and parsed data. The cache disappears when construction finishes.

Differential-row checks measure the 16 fixed footprint masks once for each geometric
scale used by that check. The table retains the exact fixture geometry and area in
square meters and acres for the assertions. Oracle requests take the ceiling of each
area in millionths of a square meter. The visibility assertions also measure each
distinct union once, keyed by its complete WKB with spatial reference. This preserves
boundary order and coordinate details that a topological key could discard. Each
generated history and omission variant still constructs its concrete inputs and runs
the production geometry operations and response comparisons. The check performs `O(M)`
fixed-mask measurements for `M` masks and `O(U)` ring-union measurements for `U`
distinct encodings. The tables are local to one conformance check.

The numerical publication check removes duplicate boundary cases only when their
binary64 operands and original units match exactly. The stateless Lean adapter sends
each distinct complete request once and expands the answers in request order. Every
distinct production input is evaluated and compared with its own answer. For `C`
retained cases and `U` distinct encoded requests, the adapter retains `O(C)` request
references and `O(U)` answers.

Source digest conformance obtains the proved content value from Lean once per frame.
The reply begins with the schema length, followed by the schema and the canonical row
order. The length fixes the boundary between schema and rows, so comparing the replies
preserves all 6,441 pair assertions, including differences in schema and row
multiplicity.

Identity transfer sends one inventory of ordered history queries, lineage, and current
claimants. Lean shares each claimant's immutable reachable history list. Its reply
contains the whole-publication winner row followed by one row per isolated claimant.
For histories 7 and 2, if claimant 1 reaches 7 and claimant 2 reaches both and has higher
priority, the rows are `[2, 2]`, `[1, -1]`, and `[2, 2]`. Lean proves equality with the
original queries, including empty inputs and repeated history tokens.
[Oracle proof](../../tests/formal/lean/OracleIdentityTransfer.lean).

The adapter checks the exact reply width before comparing every claim and winner. For
`F` claimants and `H` history queries, the inventory builds `F` reachability lists and
emits `(F + 1) * H` values. The optimization scores `(1, 0, 1, 2, 1)`, totaling 5 for
ordered observations, extensional equality, shared representation, and strict reply
validation. [Python adapter](../../tests/formal/helpers/identity_transfer.py).

The ordinary ranking matrix supplies the empty Holding subset. The Holding check
crosses the same inputs with each of the seven nonempty subsets, covering all 3,840
distinct configurations between the two checks. The associated-output check copies
each exact ordered source frame before it runs the summary and report builders.
It still checks all 420 outputs against the corresponding Lean association replies.

The log-seeking check shares fixture bytes across queries with different time bounds.
It keeps one pair of plain and compressed files for complete images and another pair
for unfinished tails. A pair can serve another query only when the complete input
bytes match, including any unfinished tail. Each query still opens both real files,
seeks its original byte stream, and compares its own ordered Lean reply. In the
finite inventory, 3,840 queries write 956 images in each format. The fixture keeps
only the two current raw images for comparison.

Each formal worker also retains up to 128 small ordered request batches for the same
compiled executable. The key includes the executable's file identity, size, and
nanosecond modification and change times. Only successful batches with the expected
number of responses enter the cache. Each caller receives its own list in request
order, so sharing Lean answers still leaves each production check to run and compare
its own result. A replaced executable requires a fresh response.

Spatial-reference selection measures projected coordinate ranges once per CRS in each
test case. Every candidate set still passes through the actual classifier and selector.
Geography publication reads each immutable reference layer once, shares a copy for
each comparison, and computes the unchanged runtime fingerprint once. It continues to
compare all staged layers, observe actual file replacement, and match each recovery
trace against TLC. Runtime invalidation has its own conformance check.

The simulated DOM retains parsed selector and class strings. Every query still walks
the live descendant tree in document order and checks each candidate's current ancestor
chain. A first-match query stops when it finds its result. For example, after a row
moves to another time window, its new parent determines whether it matches
`.section .update`. The cache size depends on distinct strings, and each query visits
at most the descendants in its search root. The traversal scores `(1, 1, 1, 1, 0)`,
totaling 4. The test adapter uses the same limited selector syntax and retains no DOM
results between queries.

Filename-allocation checks capture each actual production choice alongside its own name
table and reference request. The reserved-name registry advances with the actual choice,
so every subsequent request describes the same concrete inputs it would receive when
checked immediately. The stateless Lean reference evaluates all requests in one batch.
Strict response counts and ordered comparisons require every allocation to agree with
its own reference result. A wrong early choice still fails its own comparison even if
later requests were constructed from that choice.

For example, an empty registry and candidates `fire`, `fire-2` produce the first request.
After production chooses `fire`, the next request records that actual reserved name and
candidates `fire`, `fire-2`, `fire-3`. Both requests can be evaluated together because the
second request needs the first production result, which is already available, rather
than an earlier oracle response. Each response is decoded using its own name table.
Batching retains `O(C)` request and case storage for `C` allocations, and reduces process
launches from `C` to one. It does not reduce the allocation inventory or assertions.

The local parsing and area-table transformations are straightforward: their history,
rule, mathematical, representation, and failure scores are respectively `(1, 0, 1, 1,
0)` and `(0, 1, 1, 1, 0)`, each totaling 3. Exact memoization and fixed finite tables add
no domain rule. The allocation adapter scores `(1, 1, 1, 2, 1)`, totaling 6: involved.
Case-specific token encoding, retained response order, and bounded batched storage need
the explanation above. The complete verification machinery retains its complex
assessment. Existing checked Lean definitions and the established stateless batch
transport cover these adapters; no model property or process protocol changes.

CLI policy tests use structured log capture when asserting failure propagation and
persisted recovery decisions. Dedicated logging checks retain real console and file
rendering. Each parameterized failure receives its own exception instance so earlier
tracebacks cannot become part of a later case's diagnostics.

## Pipeline file effects

The pipeline replay compares every complete before-and-after image. A physical witness
can serve several images when the command uses the same canonical path, exact argument,
target presence, and directory layout. Each group runs the real local operation in
five independent fixtures. One checks success and four inject the existing exception
types before and after the selected primitive. Reader inputs and checkpoint and KMZ
pairs retain separate physical checks.

For example, a pending marker replacement can begin with different old marker bytes and
different source-generation bytes. Both runs stage the same new marker bytes and replace
the same relative target. A failure before replacement retains the old marker of each
image. A failure after replacement leaves the same new marker in each. The source
generation stays equal to the original value in its own image. The transfer carries the
old target symbolically when it survives. Each image supplies its own surviving target
and surrounding files.

The binder checks the current adapter's complete syntax, the dispatch and fault selection,
and the physical fixture definitions. It also checks live code, bindings, and native
primitive identities. It extracts the ordered operations and fault positions from the
accepted source. The current Lean executable compares that schedule with the one used in
the [footprint proof](../../tests/formal/lean/PeriScribe/PipelineFileFootprint.lean)
and returns the symbolic transfers. The kernel checks that these transfers preserve the
target result, reply, and trace. The existing effect theorem extends that equality to
the full ordered replay. A changed or unavailable proof build, unrecognized source or
runtime binding, or unsupported frame uses the complete physical matrix.

The fixture creates isolated regular files with distinct paths and existing writable
target parents. The proof uses the locked Python runtime's local filesystem operations,
same-filesystem replacement, and temporary-directory cleanup on the modeled exceptions.
The representative checks still observe the exact primitive paths and arguments, the
replacement inode change, and the bytes and metadata of untouched siblings. The target
parent's modification time may change as the stage is created and cleaned up. The
independent sibling corruption regressions and hard-process recovery tests continue to
exercise the real files and fault boundaries.

The footprint adapter scores `(1, 2, 2, 2, 2)`, totaling 9. It checks an ordered frame per
effect, coordinates the physical success and faults, and publishes only complete witness
receipts in the current evidence session. For `N` complete effects with `F` frame entries
and `G` physical groups, comparisons take `O(NF)` time. Physical execution visits `G`
groups, and receipts retain `O(G)` transfer results plus the reader and publication cases.
In the current corpus, 3,365 full images use 66 groups. The 50 reader inputs and 31
publication pairs are separate.
See the [binding](../../tests/formal/helpers/pipeline_file_footprint.py),
[physical verifier](../../tests/formal/helpers/pipeline_effect_matrix.py), and
[fallback regressions](../../tests/formal/conformance/test_pipeline_effect_matrix.py).

The ordered physical comparator also observes the raw reads returned to the real
coordinator and fixture. It records bytes, existence, stamps, file identities, and the
complete missing-file reply with its path relative to the private year. Each read keeps
its occurrence number. The ending count detects a removed read even when the durable
image stays the same. The original coordinator still runs for every history in the
selected batch. Its raw replies and complete frame changes are compared independently
in order, along with its injected interruptions, stage dispatch, and surviving TLC path.

The [ordered witness binding][ordered-witness-binding] qualifies the raw ports, the
fixture callbacks, and the production functions reachable under the fixture's
substitutions. The clock is fixed, the execution cache is inactive, and the isolated
year has regular files and one writer. The [mixed read and write proof][ordered-witness-proof]
composes the target-local read replies with the write transfers and preserves the
frame observations and fault replies. A changed source, substituted live binding, stale
proof build, or unsupported file effect uses the original complete physical comparator.

The [ordered witness selection][ordered-witness-selection] covers the exact read
requests and replies, write arguments and target images, failure boundary and full
failure frame, and stage/force dispatch. It runs each chosen history through its real
ancestors on private native files. Each representative must match the original ordered
tape and complete terminal matcher. The current maximum batch has 894 logical
invocations, of which 172 run in the measured native selection. The separate copy,
physical frame, and hard-process tests keep their original native evidence.

Ordered witness selection scores `(2, 2, 2, 2, 2)`, totaling 10. It combines reply-driven
continuations, live source qualification, immutable byte frames, and native fallback.
With `E` tape events and `F` file entries, checking all frames takes `O(EF)` time, apart
from comparing the bytes themselves. The greedy cover scores `H` candidate histories at
each of `W` choices. With at most `P` prefixes per history and `R` words in each immutable
class mask, the scoring takes `O(WHPR)` time. The tapes, class masks and prefix indices
are local to this check and use `O(EF + HPR)` space.

[ordered-witness-binding]: ../../tests/formal/helpers/pipeline_ordered_binding.py
[ordered-witness-proof]: ../../tests/formal/lean/PeriScribe/PipelineFileFootprint.lean
[ordered-witness-selection]: ../../tests/formal/helpers/pipeline_ordered_replay.py

## Mutation and coverage evidence

Mutation checks first require a pristine successful baseline for the exact target test
identities and source/resource hashes. A mutant changes only the intended production
behavior in a private copy. The same unchanged test must reject it; imports, tool
errors, skipped cases, or missing results do not establish defect detection. Each mutant
runs in a fresh interpreter with its own source tree and native fixtures. Exact JUnit
identities and semantic failures establish the intended rejection, while setup and
teardown errors fail the check. The [defect
contract](../../tests/formal/defect_checks.md) records the inventory, process isolation,
failure boundaries and cost assessment.

The integrated formal runner partitions the conformance collection by complete pytest
node ID. Every exact target and all registered mutant cases must be present before the
target items move to the private pristine session. For example, a target ending in
`[chart-axis]` moves only that parameter variant. After pytest completes, the
controller checks the current session's receipt for the same complete target set and
source digests. Failed or missing pristine evidence fails the integrated run.

The combined gate runs model checks, the Lean build and the pristine session in order
while ordinary checks proceed independently. Both groups must finish before the complete
formal pool starts. Standalone conformance and mutation commands keep their ordinary
selection and prepare the same baseline on demand. Publication uses the existing corpus
lock and current-session receipt validation.

The partition scores `(2, 1, 0, 1, 2)`, totaling 6. The successful receipt must follow
collection and execution in the same evidence session. The check reuses the existing
leased publication protocol and adds no system policy. Partitioning and receipt
comparison use O(T + D) time and space for T collected cases and D registered defects,
plus the time to hash the current source tree.

The regular test runner requires successful test exits and authenticated contributions:

1. Create a fresh coverage session with its run identity, directory, and shipped source
   identity.
2. Collect Python, simulated viewer, and real-browser results. Each required contribution
   must finish successfully in this invocation.
3. Validate and combine evidence. JavaScript coverage checks the complete shipped inline
   script, precise ranges, contributor identity, source bytes, run ID, and successful
   receipts. Reject stale or mismatched receipts and partial script ranges; merge V8
   coverage before conversion and reporting.
4. Enforce all required metrics. A prior report or a different script cannot complete the
   current session. Standalone runs remain useful but cannot impersonate another
   invocation's combined gate.

### Geometry in the simulated viewer

The simulated DOM builds one private table of absolute rectangles for the attached
sections, controls, and rows. Geometry reads share its immutable rectangles while the
layout inputs match. Inserting, moving, or removing an attached node discards the table.
So does adding or removing a class that changes an attached node's layout role.
Each read checks the anchor, section and body visibility, section widths, and current
control widths. This allows direct changes to text and width fixtures to take effect.
Row scale, heading stacking, and descendant widths are evaluated on each read.
Browser-facing rectangles remain independent values, and native Chromium uses its own
layout engine.

The layout adapter scores `(2, 1, 1, 2, 0)`, totaling 6. It tracks which DOM writes
end the lifetime of a shared table and uses indexed lookup for its rectangles. For
the viewer's disjoint sections, rebuilding takes O(N) time and O(R) space for N attached
nodes and R recorded rectangles.
Each unchanged measurement checks O(G) group inputs, plus the size of their control
text and the local geometry query, for G sections. Tests exercise live widths, collapse,
anchoring, class changes, reparenting, and replacement. The formal viewer histories and
regular V8 checks exercise the same shipped script with the new geometry adapter.

### Ordinary Python lanes

The default ordinary Python phase of `mise test-all` gives each file to one of four
fresh pytest sessions. Pytest applies its ordinary collection rules, doctest handling,
fixtures, and assertion rewriting within each assignment. Timing history helps balance
the files and run slower cases earlier. The current filesystem inventory determines
membership. For example, all parameter variants and doctests in one file retain the
same owner even when a previous duration is missing.

The parent accepts coverage after every assigned session has passed and published its
complete test inventory. Each session writes a private branch-coverage database in the
current run. The parent validates the assignments and combines those databases before
atomically publishing the ordinary coverage file. Cancellation stops unfinished pytest
sessions. Custom selection uses standard pytest execution.

The partition scores `(1, 1, 0, 2, 2)`, totaling 6. File assignment sorts the current
inventory by estimated cost and adds each file to the lightest lane. With F files, T
test cases, and a fixed four lanes, this takes O(F log F + T) time and O(F + T)
storage, plus coverage merging. Matched runs exercised the same 5,137 ordinary cases,
32 subtests, and measured lines and branch arcs. The concrete runner and coverage
checks exercise these verification boundaries.

### Immutable dart inputs for history fixtures

Update-history fixtures share the default dart-support table within one live invocation.
The first consumer runs the original Pillow/NumPy/Shapely implementation for all 7,201
coarse angles. Its publication records each degree angle with `float.hex()` and each
distinct immutable hull as exact WKB bytes. Readers reconstruct their own GEOS objects
and require every unique hull's WKB to roundtrip unchanged. No image, history outcome,
or assertion result is supplied by this table.

The key includes the reviewed renderer source, helper source, Python runtime, and the
actual loaded Python/native renderer artifacts, including bundled libraries. Other
application policies are outside this key and continue to execute in each history.
Each use also checks the rendering constants and live callable identities, code,
defaults, keyword defaults, closures, wrapped functions, and Pillow drawing methods.
Admission requires the original coarse callable and executable state captured when
the helper was imported, before the fixture temporarily installs its own reader.
Each identity check hashes the current artifact bytes. File size and timestamps cannot
establish byte identity: two different same-size versions can have identical metadata.
A changed renderer or live dependency takes the original native route. The source pin
must be reviewed when the rendering implementation changes. Artifacts must remain fixed
while a check reads them; concurrent modification during hashing is outside this fixture's
fixed-environment contract.

A live session lease limits the table to its producing invocation. One advisory writer
lock covers lookup and publication. A producer validates its encoding before replacing
the destination atomically; a malformed or mismatched publication is rebuilt. Each
worker seeds the original `functools` coarse cache by running its unchanged loop with
an exact default-angle lookup, restoring the original primitive immediately afterward.
Unexpected angles retain native behavior. Seeding checks every returned binary64 angle
and immutable hull reference against the verified table.

For example, two history workers still render their own distinct fire geometries and
encode their own lossless WebP outputs. Their identical fixed dart table is constructed
once and then reconstructed from exact bytes. Their history directories, durable
publications, searches, and observations remain private. Geometry, image, and cache
tests use the original functions, including their native cold-build and eviction
controls. The existing history fixture retains its setup position.

This adapter scores `(1, 2, 1, 2, 2)`, totaling 8: local memoization, interacting source
and live-binding guards, standard exact numeric encodings, deduplicated immutable
geometry, and coordinated temporary publication. With A angles, U distinct hulls, and B
total unique WKB bytes, publication and loading take O(A + B) time and storage. Each
identity check streams R renderer artifact bytes in O(R) time with a bounded hash
buffer. Binding checks have fixed size for the reviewed environment. Native geometry and
image comparisons establish the presentation-only boundary; no domain transition or
external-effect observation is replaced. Focused comparisons retain the original pytest
item/report/fixture sequence, raw production lines/arcs, and every rendered pixel and
encoded image occurrence.

Implementation: [shared table](../../tests/helpers/factories/peri_scribe/presentation/preview_grid.py)
and [history fixture](../../tests/helpers/fixtures/peri_scribe/fire_updates.py).
[Guard regressions](../../tests/tests/standard/peri_scribe/presentation/test_preview_grid.py)
exercise exact reconstruction, in-place callable changes, native fallback, source and
lease qualification, and same-size artifact changes with unchanged metadata.

## Costs, assumptions, and verification

Graph storage is `O(V + E)` in checked nodes and edges, plus typed projections and case
inventories. Prefix construction scales with total history length; replay executes
unique prefix nodes, while copying costs depend on durable bytes at each branch.
Greedy balancing is a heuristic and does not guarantee an optimal schedule. Concrete
workers own independent resources, so higher concurrency increases aggregate memory.

Shared-prefix equivalence assumes deterministic execution for the chosen inputs and an
exact copy of relevant durable state. The proof states these assumptions; concrete
regressions check copying and fresh replays. Finite model checking does not establish
unbounded correctness. Coverage shows which code executed; it doesn't establish that the
code produced the right result.

- [TLC runner](../../tests/formal/check.py),
  [process adapter](../../tests/formal/helpers/process.py),
  [session lease](../../tests/formal/helpers/session.py), and
  [checked corpus](../../tests/formal/helpers/corpus.py).
- [Graph contracts](../../tests/formal/helpers/paths.py),
  [prefix batching](../../tests/formal/helpers/pipeline_batches.py), and
  [typed corpus](../../tests/formal/helpers/pipeline_corpus.py).
- [Mutation checks](../../tests/formal/helpers/defect_checks.py) and
  [coverage validation](../../tests/helpers/javascript_coverage.mjs).
- [ReplayPrefixes proof](../../tests/formal/lean/PeriScribe/ReplayPrefixes.lean),
  [process regressions](../../tests/formal/conformance/test_process.py),
  [batch regressions](../../tests/formal/conformance/test_pipeline_batches.py), and
  [session regressions](../../tests/formal/conformance/test_session.py).
  See the [formal inventory](../../tests/formal/lean/README.md) and
  [defect-check inventory](../../tests/formal/defect_checks.md) for exact claims.

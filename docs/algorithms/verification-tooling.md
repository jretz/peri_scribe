# Verification evidence and execution

The verification tools must preserve the meaning of checked histories while sharing
expensive work. Process ownership, temporary evidence sessions, prefix replay, and
coverage receipts prevent incomplete or unrelated results from counting as success.

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

TLC configurations run through a bounded semaphore, each with private temporary JVM
and model metadata directories. Reusable conformance graph evidence requires successful
checking and validated graph decoding. Direct checks without conformance graphs validate
their registered outcome from exit status and output: ordinary success or the exact
expected counterexample. Tool failure, timeout, malformed output, or an unexpected
invariant failure does not satisfy that contract.

An invocation owns temporary corpus storage with a live lock lease and an identity
covering specifications, configurations, adapters, and checker inputs. A producer lock
admits one graph producer. Completed serialized evidence is published from private
staging; consumers reject expired or incompatible sessions. Each worker decodes its own
containers. Top-level runs start fresh sessions instead of reusing a previous run's
successful files.

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

Conformance observes complete transitions, retaining all compatible full model states
and allowed internal/stuttering paths. Individually reachable states are insufficient:
their observed order must correspond to a permitted execution. Typed graph projection
retains exact node identities and successor order.

Build a prefix tree from complete invocation histories. Identical complete prefixes
execute once; each continuation receives a private timestamp-preserving copy of the
actual durable files plus the full surviving model matcher. Terminal nodes still record
a requested history even when they have children. Weight each subtree by its invocation
count and greedily assign whole roots, heaviest first, to the least-loaded batch. This
balances work without splitting a shared prefix between workers.

For histories `[A, B]` and `[A, C]`, execute A once, copy its durable output independently
for B and C, and retain both complete outcomes. Reusing the same mutable directory lets
B contaminate C. Restarting the abstract matcher from A's visible projection can also
lose hidden choices needed to reject an impossible continuation.

## Mutation and coverage evidence

Mutation checks first require a pristine successful baseline for the exact target test
identities and source/resource hashes. A mutant changes only the intended production
behavior in a private copy. The same unchanged test must reject it; imports, tool errors,
skipped cases, or missing results do not establish defect detection.

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

## Costs, assumptions, and verification

Graph storage is `O(V + E)` in checked nodes and edges, plus typed projections and case
inventories. Prefix construction scales with total history length; replay executes
unique prefix nodes, while copying costs depend on durable bytes at each branch.
Greedy balancing is a heuristic and does not guarantee an optimal schedule. Concrete
workers own independent resources, so higher concurrency increases aggregate memory.

Shared-prefix equivalence assumes deterministic execution for the chosen inputs and an
exact copy of relevant durable state. The proof states these assumptions; concrete
regressions check copying and fresh replays. Finite model checking does not establish
unbounded correctness. Coverage measures executed structure, not semantic correctness.

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

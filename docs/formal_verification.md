# Formal Verification

Formal checks help establish specific guarantees about the pipeline, data stores,
browser, monitor, and domain algorithms. The guarantees depend on the assumptions and
bounds recorded with each check. Read this guide before designing or implementing new
system behavior, and when changing a modeled protocol, a proved policy, or the checks
that connect them to Python or JavaScript. The specifications live in `tests/formal/`,
alongside the other verification code.

## Design before implementation

Assess formal verification at the design stage for every new part of the system. For
new protocols, stateful workflows, algorithms, and domain policies with meaningful
correctness properties, model and check the proposed approach before writing its
implementation code. Apply the same ordering to changes in existing formal contracts.
The purpose is to find design errors while the approach is still easy to change.

Use [Algorithm Design](algorithm_design.md) to assess reasoning complexity and choose the
required documentation depth. That classification supplements these verification
requirements. A low score does not waive modeling, proof, or implementation-conformance
checks required by this guide.

1. State the intended guarantees, input domain, failure modes, and environmental
   assumptions independently of an implementation.
2. Add or extend the smallest useful TLA+ model or Lean specification under
   `tests/formal/`. Choose the tool by the property being checked; both are not required.
3. Run the relevant model checks or proofs and resolve counterexamples to the required
   guarantees before implementing the design. Record bounds, assumptions, and deliberate
   exclusions in the inventory. Investigate assumptions that make a property pass without
   exercising the behavior it is intended to constrain.
4. Implement against the checked contract, add conformance tests connecting the code to
   the formal definitions, and run the formal suite and ordinary tests. If implementation
   exposes a missing constraint, revise and recheck the design before proceeding.

Scale the work to the behavioral risk. Presentation-only changes and thin adapters that
introduce no new policy or state transitions may need only ordinary tests. Record why
formal verification adds no useful guarantee in the change description when omitting it
for a new component. Small code size alone is not a reason to skip modeling a protocol.

A passing check supports the stated properties under the model's assumptions and
bounds. Readers still need to assess whether the requirements are right, whether the
model includes the relevant behavior, and whether the implementation agrees with it.
Review those limits and keep the implementation checks described below.

## Running checks

Mise installs Java, the TLA+ tools archive, and Lean directly from their upstream
distributions. The configuration uses `latest` selectors; `.mise/mise.lock` records the
resolved releases, download locations, and available checksums. Lean does not require a
separate elan installation or version pin. Java uses the Temurin distribution.

| Command | Purpose |
| --- | --- |
| `mise formal` | Run all formal checks and documented counterexample checks |
| `mise formal-tla` | Explore the registered finite safety and liveness models |
| `mise formal-lean` | Check proofs and build the executable policy reference |
| `mise formal-conformance` | Compare Python and JavaScript with formal results |
| `mise formal-counterexamples` | Reproduce explicitly unsupported guarantees |
| `mise formal-defects` | Check that conformance catches selected production defects |

These tasks are independent of `mise test`. Default pytest collection ignores
`tests/formal`; conformance checks use their own pytest configuration. Formatting,
linting, and type checking still apply to the Python helpers and conformance tests.
Checks operate on temporary data and do not access fire feeds or production data.

The TLC matrix runs up to four configurations concurrently, each with private temporary
metadata, a private runtime temporary directory, and a maximum 1 GiB heap. Each checker
uses serial garbage collection and retains one TLC exploration worker and its existing
timeout. The JVM path reports one CPU to Java. TLC checks liveness on the complete graph.
Model diagnostics are emitted together on completion. If a model fails or times out,
the suite fails after the other selected configurations finish. Interrupting the runner
cancels active processes and removes their temporary storage. Set
`env PERI_SCRIBE_TLC_JOBS=1 mise formal-tla` for serial execution, or use another
positive count. The runner's `--jobs` option takes precedence over that environment
variable.

Top-level formal phases share one temporary evidence session. The model-checking phase
publishes complete graphs or complete reachable-state inventories as declared in the
model registry. The conformance checks consume that same checked evidence. Standalone
commands create their own fresh session when needed.

Twenty-six qualified configurations share immutable fields during exploration. The checker
publishes the complete graph or state inventory when the registry requires it. It
keeps counts private when the registry calls for verification without an export.
This path uses TLC's action evaluator and checks the original properties. Standard TLC
handles source or tool changes outside the reviewed bounds. The
[action frame design][action-frames] documents the qualification and the ordered
successor proof.

[action-frames]: algorithms/verification-tooling.md#immutable-tlc-action-frames

Each outer proof job owns a private POSIX process group, including tools started by
nested pytest runs. The integrated model runner leases a worker group for one active
model at a time, with fresh TLC classes, output, and metadata for each model. Cancellation
and timeouts terminate the group and drain its
output before the outer caller returns its original exception. A nested tool timeout or
cancellation aborts the enclosing job rather than allowing that nested pytest to recover.
The compiled Lean oracles and hard-crash workers run directly as leaf processes under
the same ownership arrangement. The launcher passes the group identity to tools that
start nested jobs.
Tools and their descendants must retain the inherited process group; deliberately
detached processes are outside this adapter's contract. Real-process regressions cover
these operating-system boundaries; this thin test adapter changes no modeled pipeline
protocol.

Standalone conformance and deliberate-defect tasks use six pytest-xdist workers with
work stealing. The combined test gate starts one stock pool of five fresh conformance
workers after models, Lean, pristine targets and the complete ordinary and QA graph have
passed and exited. The [phase
contract](algorithms/verification-tooling.md#fresh-conformance-admission) explains the
checks, defaults and resource assumptions. Each concrete execution retains its own
temporary storage, and Lean executables are built before workers start. In an integrated
run, workers remove each passing case's temporary files during teardown. Shared evidence
stays under the session owner until all workers exit. The twenty selected mutation
checks use one serial pristine session for the nineteen unique targets, followed by
fresh interpreter imports and private source trees for every mutant. The unchanged
assertions must pass on pristine source and reject each intended defect. Exact JUnit
identities and outcomes reject missing tests, skips and fixture failures.
Source/resource hashes bind the successful baseline to each changed tree before
mutation. These nested runs do not start another worker pool. The [deliberate defect
contract](../tests/formal/defect_checks.md) explains isolation and the independently
checked failure witnesses. Standalone conformance keeps its ordinary selection.
Individual TLC subprocesses use one model-checking worker and a maximum 1 GiB heap;
account for this and the Python processes when increasing pytest concurrency.

The pipeline composition check distributes all 19,240 complete histories, containing
38,143 logical invocations, across 48 pytest items. Identical complete prefixes execute
once. Each continuation receives an independent copy of the branch's durable file image
and the full surviving TLC path. This requires 19,240 coordinator invocations while
preserving every complete history and mutation-boundary observation. Separate physical
checks exercise distinct file effects from that run, including failure order, publication
identities, and files outside each effect's footprint. Real process crashes and selected
whole histories continue to run against actual files.

The complete raw graph, typed projections, action mappings, history catalogue, and
balanced prefix batches are prepared once per evidence session. Replay workers read
typed indexed tables with exact node identities, phase labels, and successor order.
The other raw fields remain in the checked graph used to produce those tables. Workers
avoid repeated projection parsing and history reconstruction. Regressions compare
serialized contracts with their source contracts, require independent decoded
containers, compare shared prefixes with fresh complete replays, and check copy
isolation.
`ReplayPrefixes.lean` proves composition under explicit determinism and exact-copy
assumptions. `EffectRefinement.lean` proves trace preservation under equal one-step
replies and observations. Python tests check the adapter obligations for the finite replay.

Identity feedback and coordinate-reference checks use 12 batches each, and all 38
hard-process crash scenarios are independent items. Batching preserves model bounds,
assertions, failure injection, and the checked input inventory.

Conformance consumers share complete checked evidence through typed JSON in the
current formal invocation's temporary directory. Path consumers receive directed graphs.
State consumers receive ordered state inventories or project those values from a graph
when another consumer needs its edges. TLC checks the full model in either mode.
A stable operating-system lock admits one producer. Publication uses a private staging
directory and atomic replacement after successful checking and serialization. This
reuses the completed-staging contract in `StaticDownload.tla`. Process-concurrency
regressions check the lock adapter's exclusion and failure recovery.
An owner lease and the specification, configuration, adapter, and TLC content identity
reject expired or incompatible inherited storage. Each worker retains its own decoded
read-only contract. Failed producers cannot publish partial results, and a new top-level
run always regenerates its evidence. No checked corpus is reused across runs.

Independent requests to the Lean reference run in batches to reduce transport work.
They retain their original order and exact response counts, and each case keeps its own
identity and signature tables. A request that needs an earlier response must still run
after it. Batching does not change the compiled definitions being evaluated.

Two finite conformance tests also share exact repeated production observations within
one test invocation. Incremental collection checks all 514 cases against Lean while
executing 386 distinct ordered requests. Temporal complex ownership retains all 6,591
variant checks and their graph-identity assertions, sharing 4,842 complete frozen results.
These caches preserve input order and every fixture field; they do not normalize
reversals, share mutable dataframes, or cross test boundaries. See
[Execution assurance](../tests/formal/execution_assurance.md#equal-requests-in-finite-conformance-tests).

Journal persistence fixtures supply fixed valid preview and icon images and a stable
fixture-only runtime fingerprint. The continuous builder checks and two hard viewer
interruptions exercise the full builder. The hard publication matrix shares immutable
prepared inputs generated by the same builder preparation from each exact fixture
checkpoint in the current invocation. Every crash and recovery interpreter reads its
own authoritative state before selecting those inputs and runs the same native
publication sequence. The image and environment-invalidation tests cover their own
contracts. Adapter regressions decode the actual published image payloads. See
[Execution assurance](../tests/formal/execution_assurance.md).

Formal fixtures live in `tests/formal/helpers/fixtures/`. Their aggregate `plugin.py` is
registered in `tests/conftest.py` and explicitly loaded by the standalone formal pytest
configuration, whose configuration boundary excludes that parent `conftest.py`.

Every TLC invocation, including conformance checks, sets `java.io.tmpdir` to a private
directory and removes it after the process exits. TLC extracts bundled standard modules
there; sharing that directory lets concurrent JVMs overwrite or delete each other's
modules. TLC's `-metadir` controls separate state storage and does not isolate extraction.
The formal configuration disables `pytest-slow-first`: that plugin writes a shared
timing file even when its sorting option is off, including from nested test runs.

Set `PYTEST_ADDOPTS` to override concurrency, for example `env PYTEST_ADDOPTS="-n 8"
mise formal-conformance`. Use `env PYTEST_ADDOPTS="-n 0" mise formal-conformance` for
serial debugging. `-n 0` disables distribution and runs in the main pytest process. `-n
1` also runs tests serially, but in one worker subprocess; `-n auto` chooses the worker
count from available CPU cores. Direct pytest commands using `tests/formal/pytest.ini`
have the same default and accept an explicit `-n` override. A test's own complete trace
remains sequential; parallelism distributes independent tests without reducing model
bounds or checked cases.

Use `mise install --locked` to reproduce the recorded toolchain. Use mise's upgrade or
lock-bump commands to update tools, review the lockfile, and rerun the full formal suite.
Refresh Python dependencies through uv and retain their resolved versions in `uv.lock`.
Do not introduce duplicate pins in task commands or a Lean toolchain file.

## Layout and ownership

- `tests/formal/tla/` owns TLA+ modules, TLC configurations, and `models.toml`. Every TLC
  configuration must be registered exactly once. Shared definitions may have no separate
  configuration. The manifest distinguishes verification from counterexample checks.
- `tests/formal/lean/` is a Lake project. Its modules correspond to domain concepts, and
  its executable reference evaluates the same definitions used by the proofs.
- `tests/formal/conformance/` contains tests that exercise real Python and JavaScript
  behavior against outputs of those formal definitions.
- `tests/formal/helpers/` contains reusable process adapters, fixtures, and data builders
  for the formal tests. Follow the naming, isolation, and typing rules in [Testing].
- `tests/formal/check.py` runs registered TLC models with isolated state directories and
  rejects timeouts, tool failures, and unexpected verification outcomes.

The [TLA+ inventory] and [Lean inventory] identify individual properties, implementation
owners, finite bounds, numerical abstractions, and assumptions. Update those inventories
when a model's scope changes.

## Choosing a specification

Use TLA+ for behavior across transitions: stage selection, recovery markers, competing
writers, publication decisions, journal replay, and replacement of related files. Use
it also for cache transactions, cancellation and resource lifetimes, browser refreshes,
and monitor ingestion. Use Lean for properties of pure transformations and policies over
all inputs in their stated domain. Duplication is appropriate when a policy participates
in a temporal protocol and also benefits from an unbounded theorem or an executable
reference.

State the desired property independently of the implementation. It must say something
beyond whether types agree: for example, unfinished work survives a failure, prerequisites
run in order, an algorithm agrees with a declarative definition, or recovery avoids
duplicate batches. Assuming the desired result and then proving it adds no useful check.

Keep source mappings explicit. A model may span multiple Python modules. Identify the
functions, serialized states, and effects it covers, including work deliberately outside
its scope. A link to a module alone does not establish that its implementation agrees
with the specification.

## Modeling failures and time

Model persistent writes and acknowledgments as separate actions when an interruption
can occur between them. In particular, source snapshots, pending-stage markers, geography
files and signatures, the KMZ, publication checkpoints, update journals, and viewer files
are distinct outputs. Do not assume a whole pipeline stage or publication is atomic.

Record assumptions about file replacement, cooperating writer locks, checksum identity,
valid journals, and source stability. Process termination and power loss are different
fault models; atomic replacement alone does not establish power-loss durability.

Liveness claims must name their progress assumptions. Eventual completion can require
future invocations, inclusion of the necessary stages, advancing time, and an eventual
end to failures. Do not assume progress equivalent to the property being checked.
Keep finite bounds in configurations and explain what happens beyond those bounds.
An exhaustive finite TLC run does not prove an unbounded system correct.

## Proof boundaries

Lean proofs must compile without unproved placeholders, additional axioms, or unchecked
execution shortcuts. Keep warnings fatal. The standard logical foundations used by Lean
are permitted; new domain assumptions belong in theorem parameters or explicit premises.

Ideal footprints, exact integer acreage, and elapsed-time models have deliberate domains.
They do not establish floating-point geometry, coordinate projection, unit-conversion
rounding, external source truth, or third-party library correctness. Specify boundaries
and exercise real numerical behavior in Python tests. Proving a policy implements its
specified thresholds does not establish that those thresholds are the best fire policy.
The finite binary64 [numerical policy model] explicitly covers selected rounded arithmetic
and unit-conversion decisions. Keep its finite-result and unit-metadata assumptions
separate from the ideal geometry and integer-area proofs.

## Keeping implementation and specifications aligned

For a change to a covered behavior:

1. Identify the affected model, properties, and conformance tests using the inventories.
2. Decide whether the intended contract changes. Update the specification for deliberate
   behavior changes; preserve the contract for implementation-only refactoring.
3. Extend the implementation connection with boundary cases, generated cases, or fault
   traces. Compare against the actual formal definition or TLC output, rather than a
   second handwritten Python translation of the model.
4. Run the affected formal task while iterating, then `mise formal` and the usual
   project checks before completion.
5. Document new assumptions and coverage limits. Preserve confirmed implementation bugs
   as ordinary regression tests as required by [Testing].

Conformance tests provide evidence for the executions they cover. They do not constitute
a proof that arbitrary Python executions refine the specification. Source fingerprints
and passing standalone proofs also do not establish that correspondence.

[Deliberate defect checks] strengthen this connection for selected critical guarantees.
They copy production source into temporary storage, require the existing conformance
check to pass unchanged, introduce one behavioral defect, and require that same check
to reject it. Keep specifications and assertions unchanged between those executions.
Tool failures and import errors are not evidence that a behavioral defect was detected.
Maintain these checks when the owning implementation is refactored.

For persistence protocols where order matters, compare complete observed executions
with TLC's exported transition graph. A sequence can contain only reachable states and
still put them in an order the protocol forbids. Keep compatible full abstract states
across the trace, and identify internal steps, stuttering, crashes, and environmental
events explicitly. Include a trace whose individual states are reachable but whose
ordering violates the protocol.

Retain a curated subprocess crash matrix alongside inexpensive exception injection.
Terminate at independently durable boundaries without running Python cleanup, then
recover in a fresh interpreter from the retained files. Check actual termination status
and recovery outcomes against the model. This tests process termination assumptions;
power-loss durability remains a separate contract.

## Counterexamples and failures

A failed property is a finding to investigate. Determine whether the specification,
implementation, or claimed guarantee is wrong. Do not make a check pass by removing an
action, reducing bounds, strengthening assumptions without justification, or weakening the
property without documenting the changed contract.

Some models intentionally demonstrate a limitation of the current protocol. Register
these separately with the exact invariant expected to fail, describe the source-level
sequence and practical consequence, and keep them visible in the inventory. The runner
requires an invariant violation with that name; a syntax error, tool failure, timeout,
or successful verification is not an acceptable substitute. A confirmed counterexample
does not certify the violated guarantee. When the limitation is fixed, promote its
property to the normal verification suite and update the implementation regression test.

[Testing]: testing.md
[TLA+ inventory]: ../tests/formal/tla/README.md
[Lean inventory]: ../tests/formal/lean/README.md
[Deliberate defect checks]: ../tests/formal/defect_checks.md
[numerical policy model]: ../tests/formal/lean/numerical_policy.md

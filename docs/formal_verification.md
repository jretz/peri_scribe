# Formal Verification

Formal checks describe selected guarantees of the pipeline, data stores, browser,
monitor, and domain algorithms. Read this guide before designing or implementing new
system behavior, and when changing a modeled protocol, a proved policy, or the checks
that connect them to Python or JavaScript. The specifications live in `tests/formal/`,
alongside the other verification code.

## Design before implementation

Assess formal verification at the design stage for every new part of the system. For
new protocols, stateful workflows, algorithms, and domain policies with meaningful
correctness properties, model and check the proposed approach before writing its
implementation code. Apply the same ordering to changes in existing formal contracts.
The purpose is to find design errors while the approach is still easy to change.

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

A passing check supports the stated properties within the model's assumptions and bounds.
It does not establish that the requirements are right, that every relevant behavior was
modeled, or that the eventual implementation conforms. Review those boundaries and retain
the implementation checks described below.

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
metadata, a private JVM temporary directory, and a maximum 1 GiB heap. Each process
retains one TLC exploration worker and its existing timeout. Model diagnostics are
emitted together on completion. Failures and timeouts make the suite fail after the
other selected configurations finish; interrupting the runner cancels active processes
and removes their temporary storage. Set `env PERI_SCRIBE_TLC_JOBS=1 mise formal-tla`
for serial execution, or use another positive count. The underlying runner also accepts
`--jobs`, which takes precedence over that environment variable. Top-level formal phases
run sequentially inside one temporary evidence session. The model-checking phase
publishes complete graphs for configurations used by conformance, and the later pytest
phase consumes that same checked evidence. Standalone commands create their own fresh
session when needed.

Each outer proof job owns a private POSIX process group, including tools started by
nested pytest runs. Cancellation and timeouts terminate that entire group and drain its
output before the outer caller returns its original exception. A nested tool timeout or
cancellation aborts the enclosing job rather than allowing that nested pytest to recover.
Tools and their descendants must retain the inherited process group; deliberately
detached processes are outside this adapter's contract. Real-process regressions cover
these operating-system boundaries; this thin test adapter changes no modeled pipeline
protocol.

The conformance and deliberate-defect tasks use six pytest-xdist workers with work
stealing. Each concrete execution retains its own temporary storage, and Lean
executables are built before workers start. The selected mutation checks share one
serial pristine pytest session, containing every unique target. Each mutant runs in its
own serial interpreter and private source tree. Source and resource digests must match
the passing baseline before mutation. Exact JUnit target identities and successful
outcomes reject missing, skipped, or substituted baseline checks. These nested runs do
not start another worker pool. Individual TLC subprocesses use one model-checking worker
and a maximum 1 GiB heap; account for this and the Python processes when increasing
pytest concurrency.

The pipeline composition check distributes all 19,240 complete histories, containing
38,143 logical invocations, across 48 pytest items. Identical complete prefixes execute
once; each continuation receives an independent copy of the actual durable files and the
full surviving TLC path. Timestamp-preserving copies retain publication identities. This
requires 19,240 concrete invocations while preserving every complete history and
mutation-boundary observation. The complete raw graph, typed projections, action
mappings, history catalogue, and balanced prefix batches are prepared once per evidence
session. Typed indexed tables retain exact node identities and successor order while
avoiding repeated projection parsing and history reconstruction in workers. Regressions
compare serialized contracts with their original complete graphs, require independent
decoded containers, compare shared prefixes with fresh complete replays, and check copy
isolation. `ReplayPrefixes.lean` proves composition under explicit determinism and
exact-copy assumptions; Python tests check those adapter obligations.

Identity feedback and coordinate-reference checks use 12 batches each, and all 36
hard-process crash scenarios are independent items. Batching preserves model bounds,
assertions, failure injection, and the checked input inventory.

All conformance consumers share complete checked graphs through typed JSON in the
current formal invocation's temporary directory. State-only consumers use those same
complete graphs. A stable operating-system lock admits one producer; publication uses a
private staging directory and atomic replacement only after successful checking and
serialization. This reuses the completed-staging contract in `StaticDownload.tla`;
process-concurrency regressions check the lock adapter's exclusion and failure recovery.
An owner lease and the specification, configuration, adapter, and TLC content identity
reject expired or incompatible inherited storage. Each worker retains its own decoded
read-only contract. Failed producers cannot publish partial results, and a new top-level
run always regenerates its evidence. No checked corpus is reused across runs.

Pure Lean oracle requests are batched across independent cases, preserving their original
order and exact response counts. Case-local identity and signature tables remain private.
Requests that depend on preceding oracle responses remain sequential. This changes only
the transport of requests to the same compiled definitions.

Journal persistence fixtures supply fixed valid preview and icon images and a stable
fixture-only runtime fingerprint. Real preview selection, KMZ and snapshot
serialization, file replacement, observation, process termination, and recovery remain
active. Image rendering and environment invalidation retain their own tests; these are
outside the journal's persistence contract. Adapter regressions decode the actual
published image payloads. The fixture and transport changes introduce no new application
policy or persistence protocol requiring another formal model.

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

State the desired property independently of the implementation. Include a meaningful
claim beyond type correctness, such as preservation of outstanding work, prerequisite
ordering, agreement with a declarative algorithm, or recovery without duplicate batches.
Avoid adding formal syntax that merely restates a result as its own assumption.

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

For ordered persistence protocols, compare complete observed executions with TLC's
exported transition graph. Membership of each observation in the reachable-state set
alone does not establish that their order is permitted. Keep compatible full abstract
states across the trace; explicitly identify internal steps, stuttering, crashes, and
environmental events. Include a trace whose individual states are reachable but whose
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

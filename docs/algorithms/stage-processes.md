# Supervised stage processes

A run that crosses from geography into scoring uses two sequential worker processes.
The geography worker exits before the scoring worker starts. This returns geography's
native allocations and Python objects to the operating system while the original
command keeps ownership of the year directory throughout the handoff.

The public `run` command, stage selection, and publication rules retain their existing
meaning. Ranges that do not cross this boundary run in the command process. Source
files retain their original formats and organization; the handoff contains options and
the frozen publication input collection, not a replacement source representation.

## Assessment and contract

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Completed stage acknowledgments determine the pending suffix across both workers. |
| Rule interaction | 2 | Fetch skipping, forced rebuilding, and publication deferral determine whether the second worker may run. |
| Mathematical reasoning | 1 | Sequential composition uses a standard ordered prefix argument. |
| Scale and representation | 2 | A serialized handoff recreates options and frozen input identities in a fresh interpreter. |
| Failure and concurrency | 3 | Cancellation and process death must preserve writer exclusion across independent descriptor lifetimes. |

The total is **10, complex**. The difficult part is preserving one writer lifetime while
retiring the process that performed expensive work.

Inputs are the selected inclusive stage range, force and fetch options, optional area
and time publication thresholds, logging levels, and command identity. Area crosses the
private JSON boundary in square meters and is immediately restored as a Pint quantity;
time uses validated duration values. The first child returns either completion or the
scoring stage position and the exact serialized publication collection. The second
child must return completion. Unknown fields, invalid thresholds, malformed JSON,
unexpected continuation positions, and unsuccessful process exits cannot authorize the
next child.

The protocol assumes POSIX descriptor inheritance, `flock`, and process groups, as the
existing year-directory locking already does. Cooperating writers use the same lock
inode. Replacing the lock file externally or deliberately detaching descendants is
outside this contract. The private child entrypoint is an implementation detail, not a
second public command.

## One lease across two processes

The parent acquires an exclusive lock and retains that open file description. Each
child receives a descriptor referring to the same description. Before doing work it
checks the lock file's device and inode, verifies exclusive ownership, and registers
its process-local writer context so nested reads can safely reuse that ownership.

Every holder closes its own descriptor instead of issuing an explicit unlock. This
choice matters: an explicit unlock through either descriptor would release the shared
lock even while the other process still owned a reference. With close-only release,
the last surviving reference determines when another writer may enter.

The successful sequence is:

1. The first child initializes pending work for the entire selected range and executes
   the original stage loop through geography. Fetch and publication decisions remain
   in that loop.
2. After geography succeeds, the loop acknowledges that stage and returns the frozen
   publication inputs. The child writes its response and exits.
3. The parent joins the first child, requires a zero status and a valid response, and
   starts the second child while still holding its original lease.
4. The second child resumes at scoring without initializing the pending range again.
   It uses the first child's exact publication inputs and acknowledges stages through
   the existing protocol.
5. The parent joins the second child, validates completion, and closes its lease.

Only the parent emits the command boundary. Children inherit its run identity and
severity settings and emit the ordinary stage records. Child standard output and error
remain attached to the command's streams. Numeric child failure statuses survive;
signal exits use `128 + signal`.

## Failure boundaries

| Interruption | What remains protected | Result |
| --- | --- | --- |
| First child fails before geography acknowledgment | Parent lease and pending geography suffix | No second child starts; the command fails. |
| First child exits with a missing or malformed response | Parent lease and the actual durable pending suffix | No continuation is inferred from a partial response. |
| Second child cannot start | Parent lease and pending scoring suffix | The command fails without forgetting required work. |
| A later stage fails | Parent lease and that stage's pending suffix | Completed predecessors stay acknowledged. |
| Parent receives interrupt or termination | Parent lease until its child and process group settle | Terminate, wait up to five seconds, then kill and join if needed. |
| Cancellation arrives before process creation returns a handle | Parent lease and shielded launch task | Resolve launch, then terminate and join any created process. |
| Parent is killed without cleanup | Surviving child's inherited lease | The active child may finish its segment; no parent remains to launch the next segment. |

Repeated interrupts are deferred during bounded termination. Ordinary cancellation does
not return before its active child has exited. A hard parent kill cannot provide that
return guarantee, so the inherited child reference provides exclusion until its own
exit. Existing atomic stage publication and pending-state writes remain responsible for
their individual recovery guarantees.

For example, a forced full run initially requires geography, score, KMZ, and reports.
If geography succeeds and scoring fails in the second process, the durable pending
sequence is score, KMZ, reports, with forced rebuilding still required. Reinitializing
the second child would incorrectly put geography back into that sequence. Releasing
the parent lock between workers would instead let a competing run alter those inputs
before scoring resumed. The implementation does neither.

## Correctness and resource costs

The stage loop preserves the original order within each segment. The handoff accepts
only the boundary immediately after geography, and the second segment starts at the
following stage. Concatenating their successful acknowledgments therefore produces
the same ordered stage prefix as one loop. A child failure cannot produce a successful
handoff, and pending work is removed only by the existing stage acknowledgment.

Let `G` and `P` be the peak resident memory of the geography and subsequent-stage
workers, `S` the lightweight supervisor memory, and `H` the serialized handoff size.
Sequential workers require approximately `S + max(G, P)` resident memory, plus the
ordinary operating-system and allocator overhead. This is a lifecycle estimate, not a
hard RSS bound. The handoff takes `O(H)` memory and temporary disk space; it contains
publication identity metadata rather than geometry rows. Time is the original stage
work plus two interpreter startups and `O(H)` serialization. No parallel stage work is
introduced.

Keeping both stages in one process avoids startup but retains native allocator memory.
Forking a heavily populated interpreter complicates native-library and thread state.
Independent public CLI invocations lose continuous lock ownership and can change
publication decisions. Fresh private children give a clear memory retirement point
while retaining the original policy in one supervised command.

## Implementation and verification

- [Supervisor and private child entrypoint](../../src/peri_scribe/supervision.py).
- [Stage loop and handoff](../../src/peri_scribe/pipeline.py).
- [Inherited writer leases](../../src/peri_scribe/pipeline_state.py).
- [Checked lifecycle model](../../tests/formal/tla/StageProcesses.tla) and
  [implementation mapping](../../tests/formal/tla/stage-processes.md).
- [Complete trace conformance](../../tests/formal/conformance/test_stage_processes.py).
- [Real-process regressions](../../tests/tests/standard/peri_scribe/test_supervision.py).

The bounded model checks exclusion, continuous ownership, acknowledgment order,
preserved pending suffixes, and no work after an ordinary parent return. It includes
hard parent death, but does not promise recovery from a broken operating-system lock
implementation or arbitrary external file replacement. Real-process tests separately
check the descriptor and signal assumptions on the supported platform.

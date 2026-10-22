# Supervised stage process mapping

[`StageProcesses.tla`](StageProcesses.tla) checks the lease and acknowledgment protocol
used by [`supervision.py`](../../../src/peri_scribe/supervision.py),
[`pipeline.py`](../../../src/peri_scribe/pipeline.py), and
[`pipeline_state.py`](../../../src/peri_scribe/pipeline_state.py). The design was checked
before the implementation was written. The finite configuration explores three
ordered stages, two sequential worker segments, one parent, and one competing writer:
199 distinct states and 354 generated states in the initial successful check.

The stage positions stand for geography, score, and KMZ. Reports uses the same final
segment loop and acknowledgment rule; real-process tests also exercise it. Fetch's
unchanged-input decision appears as `Skip`, permitted only without required work.
Publication gating and atomic stage publication retain their existing models.

## Bound variables

[`helpers/stage_processes.py`](../helpers/stage_processes.py) retains every checked graph
node, edge, initial state, and action. Its path projection binds every model variable:

| Model variable | Concrete observation |
| --- | --- |
| `parent` | Entry, active supervisor scope, join/error boundary, and actual lease exit. |
| `child` | Actual selected-segment entry, return, or exception under the adopted descriptor. |
| `parentLease` | `fstat` of the currently owned parent descriptor. |
| `childLease` | `fstat` of the real duplicated descriptor owned by `inherited_lease`. |
| `segment` | Original request or the actual coordinator's scoring continuation request. |
| `nextStage` | One plus the number of independently observed successful acknowledgments. |
| `completed` | Actual `complete_stage` calls after domain work returns successfully. |
| `pending` | The real `run_state.json` remaining-stage sequence after each observation. |
| `required` | The scenario's initial actual pending requirement. |
| `response` | Actual segment return, fetch skip, or injected transport failure. |
| `outcome` | The real coordinator's success, failure, or interruption result. |
| `competitor` | A real competing `run_lock` acquisition after the supervisor releases. |

The adapter executes the real coordinator, request decoder, selected-stage loop,
publication collection, descriptor adoption, and durable pending-state operations.
Domain workloads produce isolated receipt files. Process transport executes inline
under a duplicated descriptor so observations can be matched at each durable boundary;
the adapter does not replace the coordinator's continuation or pending-work decisions.

Eleven complete traces cover success, unchanged fetch, failure at each of the three
stages, cancellation in either segment, launch failure in either segment, and malformed
handoff in either segment. Every observation must extend the same complete path through
the freshly checked graph. There are no hidden lifecycle transitions. A sequence of
individually reachable states is insufficient.

## Guarantees and limits

The invariants require a live child lease during work, a continuous parent lease while
active or joining, no competing writer while either reference survives, ordered
acknowledgments, and the unchanged pending suffix after failure. Continuation requires
completed geography. Ordinary release requires a stopped child; the temporal property
disallows further stage acknowledgments after that release.

The model includes parent death and independently surviving child work. The inline
conformance adapter covers ordinary success and unwinding; the actual hard-death
boundary is checked separately by
[`test_supervision.py`](../../tests/standard/peri_scribe/test_supervision.py). Those
tests launch fresh interpreters and inject SIGINT, SIGTERM, and SIGKILL, observe actual
child process identities and exit statuses, and attempt real competing lock
acquisitions. They also check immutable publication inputs, command identity, force
flags, and failures in the final reports stage.

POSIX `flock` must associate inherited descriptors with the same open file description;
closing one reference must leave another holder protected. Lock files must retain their
inode, and cooperating writers must honor the lease. These operating-system and
cooperation assumptions are explicit; the model does not prove them. No fairness or
bounded domain-work completion is assumed. The cancellation grace interval constrains
termination attempts, not how quickly an unresponsive operating system must reap a
process.

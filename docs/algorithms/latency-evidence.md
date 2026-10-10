# Latency attribution from retained evidence

Latency reports distinguish a successful KMZ write from completion of its enclosing
command. A newly available source polygon is attributed to the first KMZ run whose
geography step could have consumed it, even when publication filtering hid that fire.

## Contract and assessment

Inputs are retained diagnostic logs, source snapshots, an identity index, and a requested
time window. Outputs are command durations and per-fire source-to-command latencies
with units. Missing endpoints do not become guessed successful completions.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Command context and snapshot arrival precede visible completion records. |
| Rule interaction | 2 | Source publication, collection, geography start, and completion constrain attribution. |
| Mathematical reasoning | 1 | Ordered joins and timestamp differences are direct operations. |
| Scale and representation | 2 | Retained logs and source versions are indexed before matching. |
| Failure and concurrency | 1 | Read-only analysis tolerates missing retained evidence explicitly. |

Total **8: involved**.

## Recover context and attribute a publication

Read diagnostic records with enough command-start context to interpret phase endings.
Maintain state by run ID; a new command start resets that run's geography and pending
write context. Record completed snapshot writes, geography starts, successful KMZ
writes, and command endpoints independently. If a completion lacks its start, reread
from an earlier context bound, including a two-second allowance for whole-second log
timestamps and rounded elapsed durations.

Extract new polygon publications from retained snapshots and reconcile their fire
identities. Order successful KMZ writes by write time. For each publication, select the
first write whose geography began after that snapshot's collection and whose known
command completion does not precede publication. Group by fire and consuming write,
retaining the earliest new publication for that pair. Emit a duration only when the
command endpoint is known.

For example:

1. A polygon is published at 09:00.
2. Run A starts geography at 09:05.
3. The snapshot is collected at 09:10. It arrived too late for Run A's geography step.
4. Run B starts geography at 09:12 and completes its command at 09:20. Attribute the
   polygon to B, yielding 20 minutes from publication to command completion.

Two new polygons for that same fire consumed by the same run yield one duration from the
earlier publication. Filtering down to logged interesting fires would answer a narrower
question and omit source observations this diagnostic intends to time.

## Costs, limits, and verification

For `P` publications and `W` successful writes, the nested matching loop is worst-case
`O(PW)` after sorting writes. Reading and decoding logs/snapshots adds work proportional
to retained evidence. Identity maps and grouped results occupy memory. A missing log
month or absent completion reduces observable results; retention is not reconstructed.
Timestamp correctness is an input assumption, and wall-clock differences need not
represent monotonic elapsed time.

- [Run evidence](../../src/peri_scribe/show_latencies/runs.py),
  [source versions](../../src/peri_scribe/show_latencies/sources.py), and
  [perimeter attribution](../../src/peri_scribe/show_latencies/perimeters.py).
- [Latency documentation](../latency_charts.md) and
  [ordinary diagnostic tests](../../tests/tests/standard/peri_scribe/show_latencies/).
- [Log-reader conformance](../../tests/formal/conformance/test_log_readers.py) and
  [log-seeking conformance](../../tests/formal/conformance/test_log_seeking.py) cover the
  shared retention/reading layer. The complete latency attribution policy is exercised
  by ordinary tests; this note adds no new behavior or formal guarantee.

# Journal recovery against actual files

Recovery has to preserve the original update records and timestamps even when it runs
again. `JournalReplay.tla` extends `UpdateJournal.tla` with observer variables that
retain a reachable interrupted journal and the result of recovering it without another
interruption. `conformance/test_journal_recovery.py` uses those checked input/output
pairs as its expected results.

The configuration has two successive batches, at most two interruptions, all four
empty/nonempty batch combinations, and both fresh/partial and gated/ungated publication
modes for each batch. With the unchanged-build rotation path included, the replay
configuration explores 78,940 states and produces 130 distinct observable recovery
relations. The recovery comparisons deduplicate cases that agree on every observed
checkpoint, journal, log, original timestamp, and age.

## One exploration for publication and recovery

Every `ReplayInit` state is an `UpdateJournal.Init` state with the same fixed observer
values. `Explore` takes exactly `UpdateJournal.Next` and leaves those values fixed.
`BeginRecovery` switches `replaying` to true. `Recover` keeps it true, so every
successor of a recovery state stays in that part of the graph. Dropping the four
fixed observer fields gives a bijection between the states with `replaying = FALSE`
and the states of the original publication model. The projection preserves every
`Next` edge, its source and target, and its position among the source's successors.

TLC checks the invariants common to both scopes across the entire graph. The original
publication-specific invariants, natural rank, and enabled progress are checked in
publication states. Rank must decrease on every nonstuttering edge between those
states. A stutter of the publication variables is also a stutter of the full state
because the observer fields remain fixed. This supplies the same premises to the
[Lean rank proof](../lean/PeriScribe/RankedLiveness.lean). Recovery keeps its own
checkpoint and publication invariants.

Builder and hard-process crash conformance use the induced publication graph from
this invocation's checked output. The adapter checks the initial marks, common
observer values, and absence of edges entering the publication subgraph. A comparison
with a separate publication exploration matched all 49,596 states, 64 initial marks,
and 80,724 ordered transitions after matching record fields by name. The recovery graph
was byte-identical with the fingerprint polynomial fixed.

## Implementation connection

`helpers/journal.py` materializes every relation as real `PendingUpdates` and `State`
JSON, plain JSONL, and Zstandard archives. Each nonempty abstract batch contains two
real fire records, so the checks distinguish whole-batch replay from per-record
duplication. They call `fire_updates.recover_updates` twice and compare the complete
retained payloads, their multiplicities, the checkpoint, journal removal, and original
timestamps with TLC's result. Distinct WebP payloads identify the mapping recorded for
each generation. A frozen clock exercises current and expired months.
The real viewer writer then reads the recovered logs and publishes its HTML and JSON.
The complete viewer payload must retain each fire's identity, current and previous
acreage, batch ID, original timestamp, and recorded preview. Expired windows must be
empty.

`helpers/journal_builder.py` additionally runs the real `kml.builder.create_kmz` and
injects process loss immediately before and after these durable boundaries:

- KMZ replacement and optional publication-checkpoint replacement.
- Update-journal replacement, batch append, and mapping-checkpoint replacement.
- Journal deletion and viewer JSON replacement.
- Archive replacement and removal of the plain log after compression.

The expanded model also separates receipt publication and retirement from archive and
source changes. This bridge retains receipt presence alongside the batch-level durable
fields above. The [rotation bridge](../log_rotation_seeking.md) also checks real receipt
contents and both sides of receipt publication and retirement, including byte-identical
diagnostic occurrences that have no batch ID.

The 50 scenarios cover fresh publication inputs and standalone/partial inputs, both
without a publication checkpoint and with one retained from an earlier KMZ. A retained
older checkpoint must fail actual KMZ-identity validation. The rotation cases first
interrupt journal publication, then interrupt recovery after the clock crosses into a
later month. Every actual replacement and deletion is observed. The resulting sequence
of projected durable states must follow one continuous path through TLC's checked graph
for that exact pair of fresh-input modes. Fresh builds cannot borrow prefixes permitted
only for partial builds. Successful retries and a further unchanged build must retain
exactly two complete batches, their original timestamps, and a valid viewer. KMZ files
are real ZIP archives and their documents are read back after publication.

The builder adapter supplies prepared geometry, report selection, publication inventory,
and a tiny XML renderer. It retains actual builder control flow, update preparation and
identity resolution, KMZ writing, publication commit, journal serialization and
recovery, monthly append/compression, checkpoint replacement, and viewer writing.
Rendering, geocoding, geography derivation, and candidate selection belong to other
tests.

The hard-process matrix checks both sides of every fresh-input publication boundary
using the same production persistence sequence. Its three prepared inputs cover the
first generation from empty state, the second generation from the first checkpoint,
and the unchanged second generation. Workers select by the checkpoint they actually
read after recovery. Separate hard interruptions before and after viewer replacement
exercise the complete builder. [Execution assurance](../execution_assurance.md)

## Limits

Recovery checks compare every distinct relation in the stated finite model. Builder
checks require selected execution prefixes to follow continuous paths through the
model's checked graph; they are not a proof that every Python trace refines every TLA+
transition. Gated coordinator modes and changing stage selections are covered separately
by the [composition checks](composition.md).

The filesystem premise is atomic replacement by a cooperating single writer with valid
input journals and archives. These checks simulate abrupt process loss at durable
boundaries, not storage corruption, power-loss durability, filesystem implementation,
UUID collisions, or an unbounded number of batches and failures. The ordinary log and
viewer tests retain calendar-boundary, malformed-record, and presentation coverage.

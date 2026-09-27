# Journal recovery against actual files

`JournalReplay.tla` extends `UpdateJournal.tla` with observer variables retaining a
reachable interrupted journal and its uninterrupted recovery result. Its checked
input/output relation drives `conformance/test_journal_recovery.py`; Python does not
reimplement the transition rules to manufacture expected results.

The configuration has two successive batches, at most two interruptions, all four
empty/nonempty batch combinations, and both fresh/partial and gated/ungated publication
modes for each batch. With the unchanged-build rotation path included, the replay
configuration explores 78,940 states and produces 130 distinct observable recovery
relations. Differences only in publication modes or other unobserved instrumentation
are deduplicated; no distinct checkpoint, journal, log, original timestamp, or age is
discarded.

## Implementation connection

`helpers/journal.py` materializes every relation as real `PendingUpdates` and `State`
JSON, plain JSONL, and Zstandard archives. Each nonempty abstract batch contains two
real fire records, so the checks distinguish whole-batch replay from per-record
duplication. They call `fire_updates.recover_updates` twice and compare the complete
retained payloads, their multiplicities, the checkpoint, journal removal, and original
timestamps with TLC's result. A frozen clock exercises current and expired months.
The real viewer writer then reads the recovered logs and publishes its HTML and JSON.
The complete viewer payload must retain each fire's identity, current and previous
acreage, batch ID, and original timestamp; expired windows must be empty.

`helpers/journal_builder.py` additionally runs the real `kml.builder.create_kmz` and
injects process loss immediately before and after these durable boundaries:

- KMZ replacement and optional publication-checkpoint replacement.
- Update-journal replacement, batch append, and mapping-checkpoint replacement.
- Journal deletion and viewer JSON replacement.
- Archive replacement and removal of the plain log after compression.

The expanded model also separates receipt publication and retirement from archive and
source changes. This bridge projects receipts away and retains the batch-level durable
fields above. The [rotation bridge](../log_rotation_seeking.md) additionally observes
real receipt contents and both sides of receipt publication and retirement, including
byte-identical diagnostic occurrences that have no batch ID.

The 50 scenarios cover fresh publication inputs and standalone/partial inputs, both
without a publication checkpoint and with one retained from an earlier KMZ. A retained
older checkpoint must fail actual KMZ-identity validation. The
rotation cases first interrupt journal publication, then interrupt recovery after the
clock crosses into a later month. Every actual replacement and deletion is observed;
its projected durable state must belong to TLC's checked state space for that exact
pair of fresh-input modes. Fresh builds cannot borrow prefixes permitted only for
partial builds. Successful
retries and a further unchanged build must retain exactly two complete batches, their
original timestamps, and a valid viewer. KMZ files are real ZIP archives and their
documents are read back after publication.

The builder adapter supplies prepared geometry, report selection, publication inventory,
and a tiny XML renderer. It retains actual builder control flow, update preparation and
identity resolution, KMZ writing, publication commit, journal serialization and
recovery, monthly append/compression, checkpoint replacement, and viewer writing.
Rendering,
geocoding, geography derivation, and candidate selection belong to other tests.

## Limits

Recovery checks compare every distinct relation in the stated finite model. Builder
checks compare selected execution prefixes with the model's reachable projections;
they are not a proof that every Python trace refines every TLA+ transition. Gated
coordinator modes and changing stage selections are covered separately by the
[composition checks](composition.md).

The filesystem premise is atomic replacement by a cooperating single writer with valid
input journals and archives. These checks simulate abrupt process loss at durable
boundaries, not storage corruption, power-loss durability, filesystem implementation,
UUID collisions, or an unbounded number of batches and failures. The ordinary log and
viewer tests retain calendar-boundary, malformed-record, and presentation coverage.

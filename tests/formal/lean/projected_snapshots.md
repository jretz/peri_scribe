# Current ownership composed with chronological snapshots

`PeriScribe/UpdateViewer.lean` adds 14 theorem declarations for complete snapshots under
current ownership. `oraclePresentationFlow` exposes the same definitions through
`projected-snapshot`. The implementation owner is `updates.snapshot_from_entries`.

## Proved composition

The model retains each original observation and performs one ownership lookup on its
durable identity. An absent mapping falls back to that original identity. A separate
current group determines which earlier acreage supplies the baseline; original log
identity and observation payload remain unchanged.

The executable collector keeps an acreage ledger keyed by current group. An independent
reference searches the complete retained raw prefix for the last observation in that
group. Their equality is proved for arbitrary raw histories, partial owner maps, and
ledger prefixes. Applying the theorem after chronological sorting establishes the entire
snapshot contract, including which records are emitted and the baseline attached to each
record. Without ownership assignments, the new collector and complete snapshot refine
the original checked snapshot definitions exactly.

Every baseline has an original retained observation as its witness; merging histories
does not sum their acreages. The last observation in a merged group replaces its earlier
baseline. Other groups cannot affect it. Records before the visible window still update
the ledger, future records affect neither ledger nor output, and equal acreage is
suppressed, including an initial zero. Emitted records retain the exact input row and
current group, fall strictly after the lower cutoff and at or before generation time,
and differ from their preceding acreage. Decreases and corrections to zero remain
visible changes.

## Implementation conformance

`test_projected_snapshots.py` compares 24,576 complete real snapshots with the compiled
oracle. Cases combine all 64 partial owner maps over three buckets with five typed
identity layouts: identifier, name, local, component, and mixed identities carrying the
same text. Maps include mergers, unchanged owners, chains, cyclic swaps, and missing
owners. Six timing patterns and six acreage patterns cover both window boundaries,
pre-window history, future rows, zero, equality, increases, and decreases. Every case
also runs in reverse input order, including equal timestamps. Additional cases use
legacy identifier/name fallback without saved log identities.

The comparison checks the full ordered emitted sequence: occurrence identity, immutable
original identity, current owner, and exact previous acreage. It also checks every other
serialized original field, presence or absence of the explicit projection, and snapshot
JSON round trips. Expected baseline and inclusion decisions come from the executable
Lean model, not from another call to production snapshot code. No production defect was
found in these checks, and no snapshot implementation change was required.

## Boundaries

Ownership maps are inputs. Their derivation, evidence retention, and alias corrections
belong to [identity transfer](identity_transfer.md). The model uses typed natural
identity tokens, integer times, and nonnegative exact acreage. Fixtures use integer
milliseconds and exactly representable eighth-acre values. Datetime parsing, arbitrary
floating-point conversion, source truth, and third-party libraries remain outside the
proof. This composition does not reassign raw logs, chase owner chains transitively, or
prove browser rendering; the [viewer inventory](geometry_updates.md) and history-transfer
browser bridge cover the latter separately.

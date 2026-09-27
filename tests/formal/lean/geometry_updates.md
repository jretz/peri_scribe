# Immutable geometry sharing and displayed update history

`GeometrySharing.lean` and `UpdateViewer.lean` use the standard Lean library. Their
executable definitions are exposed by `OraclePresentationFlow.lean` through
`oraclePresentationFlow`; both modules participate in the normal axiom audit. The
conformance tests call the real geometry pool, update-history selector, log readers,
snapshot serializer and shipped browser script.

## Compressed immutable geometry trie

The 44 geometry theorems map to `src/spatial_data/geometry_pool.py`:

- The model contains the actual compressed binary trie, its representative digest,
  highest differing bit, collision buckets, branch insertion and recursive bit routing.
  It proves highest-differing-bit and common-prefix facts using natural-number bit
  operations. It does not replace the trie with a reference dictionary.
- `Valid` requires a representative belonging to the subtree, matching prefixes above
  each split, correct child routing and strictly decreasing child split ranks. Insertion
  preserves this invariant from a valid input, including when a new branch is inserted
  above the old root. Every tree built from a nonempty insertion history is valid.
- Lookup in every reachable tree agrees with the finite map of exact digest/payload
  pairs in its insertion history. There is no post-insertion routing hypothesis on this
  result. Every exact prior payload remains present, including distinct payloads whose
  digests collide. Duplicate insertion does not add a second payload to its bucket.
- Different insertion orders with the same exact entries have equivalent lookups.
  Digest values below `2^width` imply tree height at most `width + 1`, for arbitrary
  histories and insertion orders. This follows from reachable validity and the bit
  arithmetic, independently of any conformance-time depth assertion.
- Unchanged branches persist under insertion. Immutable historical tree values retain
  their entries; the actual bridge additionally checks Python object sharing and old
  roots after subsequent mutations of the pool's current root.

`test_geometry_sharing.py` has five conformance tests. Every resulting tree node and
representative agrees with Lean across 4,042 actual insertion transitions: all histories
through length four over five digest/payload pairs, every permutation of that catalogue,
and ascending and descending sequences covering all 256 digest bit positions. Each
prefix checks exact finite-map contents, bit routing, common prefixes, representative
membership, strict split descent, unchanged prior snapshots and repeated-object reuse.
Long histories retain all old roots and recheck a spread of previous roots at each step.

Two real eight-worker pool executions issue 200 requests each, once with actual SHA-256
and once with every payload forced into the same digest bucket. They check one shared
object per exact canonical payload, complete final contents and all digest/payload
lookup combinations against the executable model. The payload catalogue distinguishes
2D/3D coordinates, two spatial references and point/line geometry.

The mathematical payload token represents complete canonical EWKB bytes, including SRID;
no digest collision-freedom assumption is used. The numerical digest abstraction matches
fixed-width, big-endian bytes, as produced by SHA-256. WKB decoding/encoding, Shapely
immutability, Python locks and the runtime's memory model are trusted boundaries with
finite implementation evidence. The pool's lock supplies the serialization assumed by
the insertion model; the proofs do not enumerate every OS thread schedule. Re-encoding
noncanonical WKB, such as another byte order, can produce different bytes and is outside
the canonical-byte reuse guarantee. Allocation failures, malformed WKB and eventual
reclamation are covered by ordinary tests rather than these proofs.

## Retained history through visible browser rows

The 30 original update theorems and 14 ownership-composition theorems map to
`src/peri_scribe/updates.py` and `src/peri_scribe/updates.html`:

- Logged typed identity takes precedence over identifier/name fallback. The history
  ledger equals an independent reference that searches the complete chronological prefix
  for the most recent same-identity record. An old record outside the display window
  still establishes the baseline; a future record changes neither output nor baseline.
- The complete snapshot equals that full-history reference after chronological sorting.
  Every emitted observation is a genuine acreage change with
  `now - window < timestamp <= now`. Unchanged acreage is suppressed, including an
  initial zero, while decreases and corrections to zero remain changes. The selected
  row retains its own baseline rather than borrowing another fire's value.
- Chronological sorting preserves every occurrence and orders timestamps. Browser
  filtering preserves the exact multiplicity of matching rows. Its five time buckets
  are disjoint and cover exactly ages from zero inclusive to 48 hours exclusive.
- Display ordering respects name rank followed by age, or age alone, and preserves all
  selected occurrences. Unique-fire counts use exactly the selected stable identity
  set, independently of repeated updates from that fire.
- Snapshot replacement consumes matching old slots one occurrence at a time. The
  complete replacement preserves the requested row sequence and duplicate count.
  Retained slots plus unused slots are a permutation of the original slots, so every
  reused node has an original matching signature. If original node IDs were unique,
  the entire replacement cannot reuse any node twice.

The [projected snapshot inventory](projected_snapshots.md) extends the retained-prefix
proof through current ownership and compares every emitted row and baseline under
merges, splits, chains, and cyclic swaps.

`test_update_viewer.py` has six conformance tests. They compare 2,269 retained
histories with real validated `LogEntry` records and quantity comparisons, checking each
selected record's complete payload and exact baseline against Lean. Cases cross older
history, strict cutoff, current and future times, equal timestamps, increases,
decreases, zero, renaming, same-named distinct fires, logged id/name/local namespaces
and permutations. Every result round-trips through the real snapshot JSON serializer.

The browser bridge checks 476 display states against the executable model using the
existing full DOM double and the shipped inline script. This includes all 169 pairs of
old/new sequences through length two over three records, exact duplicate occurrences,
renamed identities, distinct same-named fires, all 32 per-group sort patterns and their
complementary collapse patterns under four filters, and replacement of displayed
acreage/location. It checks actual DOM node identity, complete row fields and
quantities, change direction, row order and multiplicity, group identity counts,
collapse accessibility state, hidden empty groups and detachment of unused nodes. A
separate trace reads actual plain and compressed retained logs, creates and serializes
the production snapshot, then renders its rows and repeated replacements through the
same bridge.

Boundary fixtures cover one millisecond before, exactly at, and one millisecond after
zero and every bucket boundary. Explicit rendering checks the exact boundary policy.
Automatic aging checks the viewer's own scheduled callback, which intentionally runs one
millisecond after the next boundary; the DOM is not asserted to update synchronously
with the wall clock before that callback runs.

The proof treats complete valid observations, typed identities and exact acreage
equality. Acreage symbols distinguish zero from other values; the real bridge uses exact
binary fractions in eighth-acre increments. Floating-point formatting and Pint, JSON,
datetime, JavaScript `Date`/`Intl`, browser scheduling and DOM behavior remain
implementation boundaries. The browser oracle uses integer milliseconds and explicit
name-order ranks; ASCII filtering and numeric name collation are checked on the fixture
catalogue. It does not prove arbitrary locale collation, Unicode case folding,
submillisecond timestamp rounding, visual layout, animations or browser
interoperability. Equal timestamps retain input order in the modeled stable sort and
checked implementation; no permutation invariance is claimed for differently ordered
simultaneous changes. Record signatures include every displayed data field and stable
identity; unrendered batch IDs are omitted. Existing `BrowserRefresh.tla` covers the
separate HTTP refresh protocol.

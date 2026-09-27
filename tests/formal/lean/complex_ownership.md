# Temporal complex ownership

`PeriScribe/ComplexOwnership.lean` describes current ownership of component fires
through incident history and complex mergers. `OracleComplex.lean` evaluates those exact
definitions. This is an ownership policy: one wildfire has at most one current parent
complex, but its parent can change over time.

## Production correspondence

| Boundary | Responsibility |
| --- | --- |
| `geo.parsing.complex_memberships_from_row`, `geo.package.read_geopackage` | Normalize incident relationship declarations for every supported child identifier, independently of whether a row produces a complete fire record. |
| `geo.database.write_snapshot`, `geo.reading.read_snapshot_contents` | Preserve raw relationship attributes and standalone membership declarations in the parsed cache. |
| `fires.sources.read_fire_sources` | Retain each row's and declaration's source snapshot path. |
| `fires.complexes.row_observation`, `observations` | Extract assignments and explicit releases, with incident and snapshot clocks. |
| `fires.complexes.resolve`, `current_parent` | Select current direct declarations and follow aggregate mergers. |
| `fires.grouping.fire_complexes` | Construct each current reciprocal membership graph from fresh grouped fires. |
| `fires.sources.fire_is_complex_parent`, `fire_sources_from_groups` | Exclude declared aggregate identities while retaining their ordinary component fires. |

`resolve` requires fresh, unassigned `Fire` objects. `group_fire_sources` constructs
them for each grouped history. Calling it again with updated evidence constructs a
replacement graph; attempting to resolve already assigned objects directly raises an
error. The model describes whole graph construction and does not model mutation of an
older graph.

## Incident chronology and mergers

A declaration has a normalized component identifier, optional parent identifier,
incident modification time, feed priority, and snapshot serial. Parent names are
presentation metadata: a missing name falls back to the parent identifier and cannot
suppress an otherwise identifiable assignment.

1. Resolve child and parent aliases to grouped fire identities. Preserve unknown parent
   identifiers as distinct external aggregates. Ignore declarations whose child cannot
   be identified by any grouped fire.
2. Select the greatest incident time for each child. Use `attr_ModifiedOnDateTime_dt` on
   perimeter rows and `ModifiedOnDateTime_dt` on incident location rows. A polygon's
   capture time does not date its incident relationship.
3. If the incident clock is absent, use the snapshot's `lastEdit` timestamp. If neither
   clock is available, use the earliest UTC datetime. At equal effective times, incident
   location evidence outranks perimeter evidence, then the greater snapshot serial wins.
4. Identical highest-ranked declarations agree after parent alias resolution. Truly
   contradictory declarations at exactly the same rank leave the direct owner ambiguous.
5. Follow current parent assignments until reaching a terminal known or external parent.
   Thus `child → A`, followed by `A → B`, makes B the child's current owner even if no
   new child row is available. A later direct `child → C` instead follows C's current
   chain.
6. A present false `IsCpxChild` declaration releases the child's direct membership. A
   missing row, missing flag, null flag, or blank flag does not release membership. A
   positive flag without a parent identifier is incomplete evidence, not a release.
7. An ambiguous parent anywhere on the chain or a repeated identity in a merger cycle
   produces no asserted current owner. A released parent becomes a terminal parent for
   its children; releasing A from B does not itself release A's children from A.

These rules express the currently chosen incident policy. The model cannot establish
that a source's dates are truthful or that this source priority resolves every real
conflict correctly. Display names retain their first observed spelling; name selection
is intentionally outside the order-independent ownership guarantee.

Historical parent identity is separate from current member sets. When A merges into B, A
remains an aggregate even if it has no current children. Parent exclusion therefore uses
all valid historical positive declarations; otherwise an emptied parent could reappear
as an ordinary component alongside its children. Explicit releases do not erase this
history. The visibility theorem preserves every grouped identity that has never been
declared an aggregate and excludes exactly the declared known parents.

## Checked properties

The 18 theorems establish the following properties over arbitrary finite observation
lists and alias functions in their stated domains:

- The selected observations have maximal clocks; a strictly newer incident observation
  displaces an older observation regardless of source order or feed priority.
- Every selected direct assignment has supporting latest source evidence. Parent aliases
  share one identity.
- Explicit current release removes the child's owner. A merger advances traversal to the
  parent's current declaration. Revisiting an identity yields no owner.
- Forward memberships and reverse ownership are reciprocal, and a child cannot belong to
  two current parents. Returned known roots have no current parent assignment.
- Source reordering and duplicate observations preserve the selected declarations,
  direct assignment, traversal result, and current ownership.
- Parent exclusion preserves component identities exactly as described above.

`follow` is executable with explicit fuel, and theorems about traversal quantify over
that fuel. `currentMembers` and the oracle use the number of known fires plus one: each
step either terminates, detects a visited identity, or visits another known fire. Oracle
aliases target only its enumerated known fires. General sufficiency of this fuel bound
is not proved separately; conformance exhausts current direct graphs over three fires,
including unobserved/released nodes and one external parent. The Python implementation
uses a visited set and has no fuel limit.

The specification assumes grouped identity is already correct. The existing `Grouping`
proofs and their separate conformance cover identity grouping. External identifiers,
feed truth, timestamp parsing, floating-point geometry, and concurrent graph mutation
are not established by these ownership proofs. No new axioms or unchecked proof
shortcuts are used.

## Executable conformance

`conformance/test_complex_ownership.py` sends original evidence to `oracleComplex` and
compares its actual output with the production path through source extraction, identity
grouping, complex resolution, and `fire_sources_from_groups`. The Python helper encodes
inputs and projects results; it does not independently implement temporal selection or
merger traversal as an expected-result algorithm.

The bridge includes 2,197 histories: every three-observation sequence over twelve
representative observations, 250 longer seeded histories, the empty history, and
explicit undated and released-parent cases, and all 216 current direct graphs over three
fires. Each history runs in original order, reverse order, and with all evidence
duplicated, for 6,591 complete graph constructions. Cases include parent changes,
chains, cycles, self-parenting, aliases, exact ties, feed/serial priority, external
parents, unknown children, missing declarations, missing names, and clock fallbacks. The
comparison checks complete forward membership, reciprocal object links, historical
aggregate identity, and actual surviving component output.

A further 47 histories round-trip the original relationship attributes and memberships
through the actual SQLite parsed-cache schema before grouping. The same 47 histories
also round-trip standalone declarations without independently parseable fire rows,
including incident timestamps and explicit releases. Ordinary source tests also exercise
real GeoPackage reads and cached reads, including assignments and releases on rows that
cannot independently produce a complete fire record.

Eight additional histories mix parsed rows with standalone declarations in one snapshot:
an assignment to A, then B, then A again, or a release followed by reassignment and a
second release. The last declaration does not produce a fire row. These cases cross both
feeds and explicit incident dates or snapshot-clock fallback. Raw row parseability is
independent of relationship names and the oracle's evidence. Each history runs in original
order, reverse order, and with duplicated evidence, both directly and after a parsed-cache
round trip, for 48 graph constructions. Distinct clocks must survive row/membership
deduplication; an older declaration of the same relationship cannot suppress a correction.

Twelve further histories begin as real WFIGS GeoPackages and compare source reading,
parsed-cache storage, and ownership construction with the same executable Lean policy.
Both feeds include unnamed releases and transfers with a missing primary identifier, an
unknown primary plus a known secondary identifier, or repeated aliases differing only in
case, whitespace, and braces. Original, reversed, and duplicated rows each undergo cold
and warm cache reads, for 72 graph constructions. Warm reads reject a fallback to source
decoding, so agreement requires the parsed cache to retain the declaration. Oracle inputs
include every independently supplied alias; the production parser must preserve usable
secondary identifiers rather than deciding source truth from column priority. Alias
normalization and cache preservation remain sampled implementation obligations, not new
assumptions of the ownership proof.

The original chronology, merger, release, and cycle defects are retained as ordinary
regressions in `tests/tests/standard/peri_scribe/fires/test_sources_complex_history.py`;
all four failed before the production correction. These checks provide sampled
implementation correspondence, not a proof that every Python execution refines Lean.

## Oracle transport

A request is `resolve COUNT | ALIASES | OBSERVATIONS`. Alias entries are known-fire
indices or `n`; each observation is `child,parent,time,priority,serial`, with `n` for an
explicit release. Missing evidence is absent from the observation list. The bridge maps
the earliest fallback to clock zero and dated values to positive ticks without changing
their order.

The response contains one owner per fire, then a count and list of visible fires, then a
count and list of historical parents with each parent's member count and members. Known
parent `n` is encoded as `2*n`, external identifier `n` as `2*n+1`, and an absent owner
as `-1`. Parent and member lists are sorted for comparison. Transport parsing and
printing introduce no alternate ownership decisions.

# Fire grouping and current complex ownership

## Contract and context

Grouping turns retained source rows into connected fire identities. It consumes parsed
names, identifier aliases, geometry in degree coordinates, and aligned immutable snapshot
paths. It returns every input position in exactly one group, in first-encounter order.
Complex resolution then consumes incident declarations and fresh, unassigned grouped
`Fire` objects. It returns reciprocal current ownership and every historically declared
aggregate, including aggregates whose current member set has become empty.

This operates across the United States. Shared names alone do not merge distant fires.
Source-issued identifiers, internal source components, and display names have distinct
roles; none is evidence that a real-world source statement must be true.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 3 | A later release, transfer, or parent merger changes current ownership while historical aggregate identity remains relevant. |
| Rule interaction | 3 | Alias equivalence, spatial connectivity, contradictory declarations, and merger cycles interact across fires. |
| Mathematical reasoning | 2 | Spatial compatibility and connected components compose; degree distances are not constant physical distances. |
| Scale and representation | 2 | WKB deduplication and an STRtree avoid repeated geometry comparisons; source anchors distinguish anonymous components. |
| Failure and concurrency | 0 | This note covers an in-memory grouping and graph construction, without durable effects. |

**Complex, total 10.** Misgrouping changes downstream history ownership and publication,
so the identity boundary needs an explicit contract in addition to its score.

## Approach and invariants

A union-find structure joins any records sharing an identifier. Separately, for each
shared normalized name, nonempty geometries within `FIRE_PROXIMITY_TOLERANCE` (currently
0.05 degrees) are joined. Byte-identical geometries are first joined as classes; one
representative per class enters the spatial index. These classes preserve all adjacency:
a duplicate has the same spatial neighbors as its representative. The final relation is
transitive connectivity, rather than an all-pairs distance requirement within a group.

![Identifier and proximity edges establish connectivity](grouping-connectivity.svg)

*Every edge is evidence of identity under this policy. A–B–C form one component even
when A and C are not directly near. A faraway same-named D has no edge and stays separate.*

Groups select the most common mixed-case name, falling back to all spellings; exact name
count ties retain first encounter. Any active row makes the grouped fire active. All
identifier aliases survive; the canonical identifier prefers the project's unique-fire
identifier form. Spatial/time outlier diagnostics flag suspicious results without
splitting the established group: the spatial diagnostic asks whether each record has
another neighbor within one degree, not whether every pair is close. A record without
geometry disagrees when another record has geometry; a fully geometry-free group does not.

Each source occurrence has an anchor `(feed, numeric serial, filename, row token,
occurrence number)`. A row token uses object ID when available, otherwise canonical row
content. The minimum anchor supplies a hashed component ID. A merge keeps the least
anchor; after a split, only the part containing that anchor keeps its key. A newly acquired
earlier feed/anchor can change the key. All individual anchor aliases are retained for
later ownership reasoning. This is not an immutable identity for all possible regroupings.
The digest assumes collision resistance; the occurrence number distinguishes otherwise
indistinguishable copies without giving one copy a real-world identity.

Score keys use external identifier first, component ID next, and a legacy name fallback
last. Reserved external prefixes are escaped. Thus an external identifier literally
`component:abc` becomes `id:component:abc` and cannot masquerade as an anonymous component.

For complex ownership, normalize child and parent aliases, then choose the greatest
`(incident modification time or snapshot time or earliest UTC, location-feed priority,
serial)` for each child. Equal-rank distinct parents, including assignment versus release,
are ambiguous. A false child flag is a release; missing/blank flags and positive flags
without a parent are absent evidence. Polygon capture time never dates the relationship.

Follow the selected parent chain through current parent mergers. A repeated or ambiguous
identity anywhere in the chain yields no asserted owner. A terminal unknown identifier
is a valid external aggregate. A released parent can still own its children: releasing A
from B terminates a child's chain at A. Constructing the graph from fresh objects ensures
that forward members and reverse `fire.complex` agree and that each child has at most one
current owner. Unknown children are skipped. Aggregate labels keep their first spelling,
so label selection is deliberately separate from order-independent ownership.

## Worked examples and boundaries

Suppose child C declares A on Monday, A declares B on Tuesday, and C has no Tuesday row:

| Day | New declaration | Current chain from C | C's current owner |
| --- | --- | --- | --- |
| Monday | C belongs to A | C → A | A |
| Tuesday | A merges into B | C → A → B | B |
| Wednesday | A is released from B | C → A | A |

A remains a historically declared aggregate throughout. Wednesday releases A, not C;
if it instead released C, C would have no owner. A later feed snapshot repeating Monday's
incident time cannot override a newer incident statement merely because its polygon capture
or download time is newer.

Keeping every observed membership would put C in two parents after a transfer. Dropping
an empty A from historical aggregate identity would let A reappear as an ordinary fire
alongside its former children. The algorithm therefore retains declared aggregates for
output exclusion even when their current children have moved elsewhere. Conversely,
missing a row is not a declaration and cannot release ownership.

For C → A → B → A, a visited set detects the cycle and no owner is asserted for C.
Likewise, C → A and C → B at the same highest rank yield no owner: selecting the first
encountered choice would make ownership depend on source order. Shared identifiers still
merge distant geometry: spatial warnings do not override explicit identity policy.
Same-name records with missing geometry do not receive proximity edges. Source
normalization and geometry validity remain caller duties.

## Costs and limitations

For N records, I identifier occurrences, K distinct named geometries, and E nearby pairs,
identifier lookup and class assembly are linear in their input and WKB bytes. STRtree
construction is normally O(K log K) and reports O(E) candidates; dense geometries can
still produce O(K²) pairs. Union-find uses path compression without a union-rank rule;
its usual benefit must not be reported as the stronger inverse-Ackermann bound that
requires additional assumptions. Memory includes O(N + I + K + E) query/identity data.
The separate outlier diagnostic can compare all distinct geometries in a group.

For D declarations and F fires, latest-evidence selection is O(D); following chains for
every fire is O(F²) in the worst case, with O(D + F) stored evidence and graph state.
Hashing anchors also costs their serialized byte length. Tolerances are degrees and vary
in physical meaning by latitude; grouping cannot establish external identity truth.

## Implementation and verification

Owners: [grouping](../../src/peri_scribe/fires/grouping.py),
[components](../../src/peri_scribe/fires/components.py),
[complexes](../../src/peri_scribe/fires/complexes.py),
[source aggregation](../../src/peri_scribe/fires/sources.py), and
[score identity keys](../../src/peri_scribe/fires/identity.py).
Ordinary checks include [grouping](../../tests/tests/standard/peri_scribe/fires/test_grouping.py),
[component anchors](../../tests/tests/standard/peri_scribe/fires/test_components.py),
[complex histories](../../tests/tests/standard/peri_scribe/fires/test_sources_complex_history.py),
and [property-based grouping](../../tests/tests/property_based/peri_scribe/fires/test_grouping.py).

[Grouping proofs](../../tests/formal/lean/PeriScribe/Grouping.lean) establish undirected
connectivity for symmetric edges, with explicit parent-pointer refinement obligations.
[Component identity](../../tests/formal/lean/component_identity.md) and
[temporal ownership](../../tests/formal/lean/complex_ownership.md) document anchor,
alias, release, merger, and output-visibility guarantees. Their bridges are
[grouping](../../tests/formal/conformance/test_grouping.py),
[component identity](../../tests/formal/conformance/test_component_identity.py), and
[complex ownership](../../tests/formal/conformance/test_complex_ownership.py).
These prove abstract policies and sample implementation correspondence; they do not prove
GEOS, timestamp parsing, identifier truth, or hash collision resistance. Complex traversal
uses fuel in Lean and a visited set in Python; the inventory records that boundary.

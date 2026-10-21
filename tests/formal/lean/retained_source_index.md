# Retained source dependency index

[`RetainedSourceIndex.lean`](PeriScribe/RetainedSourceIndex.lean) checks the invalidation
contract before the persistent index implementation. It uses occurrence identities,
complete evidence identities, and finite undirected dependency edges. The domain is
unbounded natural-number identities; proof premises state the relationship to source
evidence explicitly.

## Guarantees

Eleven theorems establish the following properties:

- Changed occurrences are exactly the entries whose complete optional evidence differs.
  Optional absence represents insertions and deletions.
- The executable affected predicate equals reachability from changed occurrences in the
  union of the previous and current dependency graphs.
- Changed occurrences seed their own closure. Following either graph preserves impact,
  and no previous or current dependency edge crosses the dirty/clean boundary.
- Filtering the closure to current occurrences excludes deleted rows from hydration.
  Any occurrence outside the closure retains its complete evidence identity.
- Replacing complete dirty blocks with current edges while retaining complete clean
  blocks has the same edge relation and connected components as an independent full
  current index, provided unchanged complete evidence preserves clean edges.
- Conservative dependency coverage and stable edge decisions for equal complete
  endpoint evidence discharge that clean-edge premise for the computed closure.
- An order-preserving compact rank selects the same original minimum in every subset
  of its complete catalogue.

The last premise is a source interpretation obligation, not an assumption that the final
partition is correct. Identifier and tagged-name incidence must conservatively contain
every grouping edge. Their current numerical geometry policy remains covered by
[`Grouping.lean`](PeriScribe/Grouping.lean) and its existing concrete conformance tests.
The blockwise replacement theorem permits exact cached local partitions to supply those
edges while preserving the complete component relation.

The compact-anchor theorem assumes preservation of the complete original order. It does
not prove Python's rank construction, uniqueness of a source/serial/filename prefix, or
the component digest. Generated
[subset checks](../../tests/property_based/peri_scribe/geo/test_source_summaries.py)
compare every nonempty subset's compact anchor choice and digest with the complete
original anchors. These ordinary checks supply evidence for the thin rank adapter;
the theorem states the mathematical consequence of its order-preservation obligation.

## Persistence boundary

The retained index serializes complete metadata and its reverse incidence map together
as one authenticated product. Strict validation reconstructs the expected reverse map
from rows and rejects omissions, extra references, duplicate occurrence identities, or
different ordering. A missing or invalid previous index marks every current occurrence
for preparation.

The reverse index never authorizes a partition by itself. Each reused partition still
requires its complete current ordered evidence key, runtime policy, receipt, and valid
local-position partition. Classification misses independently require their group's
complete rows. The grouping and classification policies remain unchanged.

Completed partitions and the completed current reverse index are published inside the
same owning product-cache transaction. The existing
[`ProductCache.tla`](../tla/ProductCache.tla) protocol covers that transaction's atomic
publication and abort. There is no separate durable index file or intermediate manifest
acknowledgment, so this change introduces no additional independently durable transition
requiring a second temporal model. Source checksums and product receipts retain their
documented authentication assumptions.

## Implementation connection

The executable presentation-flow oracle evaluates both exact changed occurrences and
the same affected definition used by the proofs. Concrete conformance constructs all
125 three-occurrence inventories over five symbolic states: absent, key A, key B, both
keys, and key A with changed complete evidence. It compares every previous/current pair
with production `changed_rows` and `affected_rows` after serialized index round trips.
Repeating with identifier/identifier and identifier/name tags checks 31,250 histories,
including bridge insertion, bridge deletion, unchanged inputs, metadata-only changes,
and identical text in different incidence kinds. Missing-index fallback is checked for
each inventory.

These finite tests connect production reverse-map traversal to the unbounded path
definition. They do not prove arbitrary Python executions, SHA-256 collision resistance,
external source truth, or GEOS numerical predicates. Ordinary integration tests compare
selective hydration with complete source-index preparation and exercise product-cache
interruption at actual transaction boundaries.

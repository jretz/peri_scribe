# Exact proximity forests

`GroupingForest.tla` models discovery over an arbitrary undirected graph independently
of the spatial index. The graph is chosen from every subset of the six possible edges on
four vertices. Every seed, pending-vertex admission and active-neighbor discovery is
explored. No action may finish a vertex while it still has an undiscovered true
neighbor.

| Configuration | Bounds | Checked properties |
| --- | --- | --- |
| `GroupingForest.cfg` | Four vertices; all 64 simple undirected graphs; every frontier/seed order | Every emitted edge is real; no vertex is discovered twice; completed vertices have no active neighbor; the final forest has exactly the graph's components; at most three forest edges are emitted. |

The initial design check explored 5,176 generated states and 4,314 distinct states. The
complete graph, initial states and successor edges are regenerated for formal
conformance; those counts are evidence for this configuration, not an unbounded proof.
The model checks safety and terminal results. It does not claim liveness without a
progress assumption, and stuttering or an interrupted computation need not finish.

The implementation boundary is `fires.proximity.spanning_pairs`. Its active bounding-box
tree must provide a conservative superset of undiscovered exact neighbors; exact GEOS
`dwithin` decides every accepted discovery. `Grouping.lean` supplies the unbounded
forest-path and component-locality theorems under their explicit coverage premises.
Neither specification proves GEOS, floating arithmetic or Python's mutable counters.

`test_grouping_forest.py` consumes the complete freshly checked TLC graph and realizes
every abstract input using concrete multipart polygons. Every vertex has a private
square and shares one additional square only with each incident neighbor. Distinct
gadgets are farther apart than the degree tolerance, so this construction realizes all
64 arbitrary adjacency graphs without assuming polygon distance is a metric. The test
first checks that exact GEOS predicates reproduce the input edges, then forces the
active-tree implementation and requires its complete forest among the model's admitted
terminal results for that exact graph. This is an output correspondence check for a pure
algorithm; it makes no claim about persistence transitions.

Ordinary and property checks additionally cover dense large inputs, envelope false
positives, empty/nonfinite envelopes, exact tolerance boundaries and arbitrary local
points and polygons. The dependency partition cache reuses the separate existing
product-cache transaction protocol and is checked against the executable Lean grouping
definition on misses, repeated hits and changed evidence histories.

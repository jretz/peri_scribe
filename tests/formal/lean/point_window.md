# Adaptive longitude windows

`PeriScribe/PointWindow.lean` models temporary point-tile selection independently of
storage, polygon topology, and the query-count heuristic. Points and envelope limits
are arbitrary signed integers. Lists retain point multiplicity and original ordering.

## Properties and implementation mapping

| Checked definition or theorem | Implementation and obligation |
| --- | --- |
| `window` | `LongitudeIndex.select` uses binary-search endpoints denoting the sorted list after dropping longitudes below the minimum and taking longitudes through the maximum. |
| `drop_lower_equals_filter` | Sorting ensures that dropping the low prefix retains exactly the occurrences at or above the minimum. |
| `take_upper_equals_filter` | Sorting ensures that the first longitude beyond the maximum ends the entire qualifying prefix. |
| `select_equals_filter` | Longitude-window selection followed by inclusive latitude filtering equals all four envelope comparisons on the sorted points. |
| `selected_bag_preserved` | A sorting permutation preserves every selected occurrence, including equal endpoint coordinates. |
| `exact_counts_preserved` | Any unchanged exact containment predicate produces the same integer count from either candidate bag. |
| `sorted_points_ordered` | The executable reference establishes numeric ordering through Lean's merge-sort theorem. |
| `candidates_preserve_exact_counts` | The complete executable sort/window/filter path establishes both ordering and permutation premises itself. |

`OracleSpatial` accepts `point-window` followed by four comma-separated bounds and
zero or more comma-separated longitude/latitude pairs. It returns flattened selected
pairs from the same `candidates` definition covered by the theorem. There is no
parallel Python reference replacing these formal outputs.

The [conformance test](../conformance/test_point_index.py) checks every bag of length
zero through two over nine signed grid points, combined with every four-bound envelope
over the coordinate values -1, 0, and 1: **91 × 81 = 7,371 cases**. These include
reversed envelopes, repeated coordinates, equal longitude with different latitude,
empty input, and exact endpoints. Comparison uses multisets because NumPy may choose
a different ordering for equal longitudes while preserving count semantics.

The existing [spatial index conformance](../conformance/test_spatial_index.py) retains
the tile completeness and strict rectangle-containment checks through real SQLite
payloads. Ordinary integration tests exercise the adaptive and direct branches with
duplicate points, polygon holes, empty inputs, unchanged database bytes, and cleanup
after containment errors. Signed int32 extreme coordinates are covered separately by
ordinary helper tests.

## Boundaries and assumptions

The unbounded theorem proves a mathematical list algorithm. NumPy sorting must be a
permutation ordered by longitude, and its binary searches must denote the same lower
and upper cuts. The concrete int64 longitude representation exactly includes every
source int32 value; array shape and native integer coordinates are input assumptions.
The finite conformance cases test these adapters without proving NumPy itself.

The point store's existing quantization, tile enumeration, and coordinate conversion
remain separate contracts. GEOS containment, projection, malformed geometry behavior,
SQLite I/O, allocation failure, and operating-system resource cleanup are not proved
here. `contains` is an arbitrary unchanged predicate in the count theorem; proving bag
equivalence does not establish geographic truth or numerical robustness of that
predicate.

The threshold of eight chooses a strategy with the same candidate bag. It is not a
mathematical bound on memory or a proof of optimal runtime. The temporary index does
not add durable state or concurrency behavior needing a separate protocol model.

The new proofs and executable oracle were built successfully before implementing the
Python helper. Both the ordinary tests and formal conformance must continue to run when
changing its representation or search endpoints.

# Cache dependency completeness

`PeriScribe/CacheDependencies.lean` models a key's structured preimage as an ordered
projection of named input fields. It proves that a key preserves every declared
semantic dependency **if and only if** every required field is included. Omitting one
admits a constructive false hit: two inputs with equal keys and different required
values. Complete keys preserve any deterministic function of those dependencies;
combining complete dependency sets covers their union. Wrapper fields can change while
content is reused, provided the current wrapper is reattached.

These theorems quantify over arbitrary field lists and natural-number input values.
Field numbers abstract exact serialized values; they do not abstract a numerical
measurement by rounding it. Equal source values are equal tokens. Hash collision
resistance, serialization fidelity, and the completeness of the declared dependency
inventory are explicit implementation assumptions, not conclusions of the theorem.

## Production correspondence

`helpers/cache_dependencies.py` declares the following contracts independently of the
production key functions. `conformance/test_cache_dependencies.py` compares each real
lookup's context/key equality and authenticated hit with `oracleCache`, then compares
the complete cached result with a fresh uncached computation. Every transition starts
with a real miss and a verified real hit on the unchanged inputs. Each computation
owns a new execution scope; mutating objects inside an existing memoization scope is
outside the owned-input contract.

| Product | Key dependencies exercised | Deliberately live or irrelevant fields |
| --- | --- | --- |
| `presentation.selection.prepare_histories` | Complete selected row values, row order, schema, CRS, geometry, canonical alias identity, area policy | DataFrame index labels |
| `presentation.text.fire_description` | Index metadata, latest perimeter and point facts, complete supplied prepared history, geometry | Current score explanation reattached after reuse |
| `kml.plot_rendering.render_plot_request` | Series values, times, stroke styles, colors, labels and order, axis label, renderer settings, timezone environment | Current filename and bundle position |
| `kml.plot_rendering.plot_image_bundles` | Each chart's complete drawing inputs | Current fire order and filename association |
| `fires.spatial_products.buffered_geometries` | Exact geometry, buffer distance, projection, enclosing runtime context | None |
| `fires.spatial_products.building_counts` | Query geometry, replacement point-database bytes at the same path, enclosing runtime context | Dataset path alone is not content identity |
| `kml_io.fragments.BoundaryCache.boundaries` | Exact component coordinates/order, SRID, formatter precision | Presentation wrappers are owned by callers |
| `kml.fire_data.added_areas_for_rings` | Exact ordered ring geometries | Observation time labels do not affect area |

The bridge preserves all serialized history and description fields, exact SVG and KML
fragment bytes, exact WKB, integer counts, and unrounded area quantities. Cases include
an explicitly supplied empty prepared history and a change of original area units within
that history. Both invalidate descriptions while preserving exact fresh results through
canonical decoding and domain validation. These cases retain the existing dependency
contract and introduce no new cache protocol or domain policy.
Dependencies may conservatively invalidate even when one particular mutation leaves the
rendered result unchanged; sound keys need not be minimal keys. A wrapper-only mutation
must reuse content while producing the current wrapper in the complete result.

`helpers/cache_chart_bundles.py` checks all six permutations of three fires with zero,
one, and two distinct charts. It requires persistent hits with stable per-owner keys,
checks each current filename and SVG payload against its source owner, and compares
the complete cached bundles with fresh rendering. Building-data mutation replaces the
database at the same path, so a key accidentally depending only on its pathname cannot
satisfy the invalidation check.

`helpers/cache_context.py` additionally connects the enclosing runtime fingerprint to
the same Lean dependency obligation. It changes equal-length source bytes in each of
the eight included packages independently, then changes Python, platform, GEOS, PROJ,
and a dependency-library version. The product bridge separately verifies that a changed
runtime context prevents reuse of otherwise identical spatial product keys.

## Boundaries

This is a necessary-and-sufficient theorem about declared dependencies plus finite
implementation conformance, not a proof that every Python renderer has no undeclared
input. Row serialization, building-store schema metadata, and locale behavior retain
their dedicated ordinary dependency tests in addition to the formal bridge's cases.
Classification and full geography reuse also have source-key and publication checks;
this module does not prove their numerical algorithms. Geometry libraries, locale
implementations, timezone databases, and external dataset truth remain trusted.

Certified ring areas take a separate path: supplied measurements accompanied by the
matching complete sequence digest are accepted as previously computed evidence. The
cache bridge exercises the fallback computation and persistent cache, not the truth of
arbitrary caller-supplied certified values. In-memory boundary caches assume the same
formatter for their lifetime. These contracts do not authorize changing a renderer
callback while retaining an old cache under an unchanged key.

## Executable reference

`oracleCache` accepts four pipe-separated lists of natural numbers: required fields,
key fields, old input values, and new input values. It returns three Boolean integers:
dependency completeness, key equality, and required-input equality. The executable
uses the same projection definitions appearing in the proofs. No Python copy of the
formal decision is used as the expected result.

## Complete source keys and classification

`helpers/source_cache_dependencies.py` connects the same Lean dependency projection to
`fires.reuse.fire_keys`, `shared_fire_keys`, and
`fires.index.classifications_for_prepared_sources`. Its 25 transitions include full raw
attributes and their value types, object identifiers, source names and relative paths,
observation order and removal, every parsed `FireRecord` field, grouped aliases, parent
identity and label, and the aggregate's member set. Membership changes pass through real
source grouping. The grouped-alias case varies that field independently of raw record
identifiers so an omitted grouped dependency cannot hide behind row invalidation.

The bridge uses real source fingerprints, persistent SQLite misses and hits, projection,
geometry signals, and complete classification serialization. Every unchanged baseline
must hit; every declared dependency mutation must miss; changed results must exactly
match a fresh uncached classification. Attribute dictionary insertion order deliberately
retains the key. Conservative invalidations are allowed: changing a raw attribute or
membership need not change this particular classification's output.

Administrative boundary loading uses a synthetic projected box and border, keeping all
classification algorithms real and the checks offline. Boundary-byte mutation also
changes that synthetic geometry. A private source tree permits deterministic code-byte
mutation without modifying repository sources. Real derivation-context hashing covers
those boundary and code bytes; the enclosing product-store runtime context is varied
separately. These cases do not prove that every future classification setting is included
in the context or verify administrative boundary acquisition.

The prepared read includes a second component used to change the selected component's
aggregate membership. Classification selects one component, matching the production
subset used when only some cache entries miss. Each computation rebuilds grouped objects
and owns a fresh execution scope. Mutation of retained inputs during one owned scope and
arbitrary disagreement between supplied records and their grouping remain outside this
bridge. Numerical correctness retains the separate border-classification checks and
geometry-library assumptions; the additional claim here is reuse correctness for these
concrete dependency changes.

# Perimeter geometry: border evidence, rejection, and cleaning

## Contract and context

Two related geometry boundaries determine which perimeter is retained and what is drawn.
Border classification combines source-specific projected geometry, contemporary source
extents, and identifier evidence to choose a geographic class used by
[reconciliation](perimeter-reconciliation.md). After reconciliation, size validation and
cleaning remove collapsed mappings and rendering artifacts from derived geometry while
leaving source files intact. These are nationwide operations; the California boundary
exists because one available feed has a regional coverage preference.

## Complexity assessment

| Dimension | Border policy | Cleaning and size policy | Concrete reason |
| --- | --- | --- | --- |
| History and state | 2 | 0 | Border extent selects the freshest observation per feed before comparing clocks. |
| Rule interaction | 2 | 2 | Geometry outranks weaker signals; collapse ratios, tiny-part fallback, and hole removal have distinct boundaries. |
| Mathematical reasoning | 2 | 2 | Projection, union, area ratios, topological simplification, and geodesic size measurement have different domains. |
| Scale and representation | 2 | 2 | Border deduplication avoids repeated reprojection; whole multipart cleaning preserves inter-part topology. |
| Failure and concurrency | 0 | 0 | The algorithms operate on supplied in-memory geometry. |

**Both involved: totals 8 and 6.** Their output affects source selection and measured
published geometry, so this note records explicit numerical and policy contracts.

## Border evidence and invariants

Each source has a declared CRS; transform it to California Albers with longitude/latitude
axis order fixed. The reference box follows California's interstate border and closes far
into the ocean and Mexico. Therefore its area predicate concerns this box, not all legal
state boundaries. Collapse byte-identical `(source, geometry)` pairs before projection.
Use the union of distinct shapes, except that wholly one-sided collections can retain
parts: the area fractions are exactly 0 or 1 and the minimum part distance is the union
distance. Outside absolute area still needs a union so overlapping parts count once.

For a positive-area union, let I be inside area, A total area, and O = max(0, A − I).
Crossing requires I/A > 0 and either O/A > 0.01 or O > 500 acres. Noncrossing geometry is
near when border distance is at most 10 km; inside means I/A ≥ 0.5. Empty geometry gives
zero fractions, infinite distance, and no crossing/near/inside evidence. Nonempty points
and lines also have zero area fractions, but their distance can establish nearness.

![Geometric evidence controls crossing](perimeter-border-evidence.svg)

*The schematic cases separate area evidence from distance and identifiers. Only positive
area on both sides meeting an outside threshold establishes crossing; an identifier
never promotes a fire to crossing.*

Compare only the freshest nonempty FIRIS and WFIGS perimeters, ranked by observation time
then serial, with first input retained on exact ties. They must be within 24 hours; two
undated observations can be compared, while one dated and one undated cannot. Extent
conflict requires positive FIRIS area and either WFIGS/FIRIS > 1.05, or larger WFIGS area
and symmetric-difference area > 0.05 × FIRIS area. Do not search older records merely to
find a compatible pair.

Classification precedence is crossing, then near (geometric near or extent conflict),
then inside/outside. An out-of-state unit, mission, or origin only records an evidence
flag and does not change the class alone. This prevents weaker administrative evidence
from asserting a physical crossing. The one-sided collection shortcut preserves the
same scalar geometry signal as true union, rather than merely the same final label.

## Size filtering and cleaning

Reject a measured perimeter when its area is strictly less than 20% of the first positive
computed-area attribute, or strictly less than 1% of the first positive incident-size
attribute. Geometry is measured geodesically; both references use acres. Missing measured
area provides no rejection evidence. Equality at either fraction is retained. The looser
incident threshold allows genuine reporting to run ahead of mapping.

Cleaning uses degree coordinates and configurable defaults: part/hole area floor
10⁻⁶ degrees², collinear epsilon 10⁻⁷ degrees, and nominal deviation 22 meters. Retain
polygon parts and holes strictly larger than the area floor. If all polygon parts fall
below it, keep the original entire geometry: a wholly tiny fire must not disappear as
noise. Empty, missing, and wholly nonpolygonal inputs also pass through unchanged.

![Rendering cleanup and the whole-fire fallback](perimeter-cleaning.svg)

*Copies slide from the original geometry into the derived result. The tiny detached
part dissolves while the tiny hole fills, showing the two different effects of dropping
below-floor area. In the lower case, the whole small fire arrives unchanged because no
substantial part would survive. Sliding represents copying, not geographic movement.
The labeled input and result also show both cases with reduced motion. This schematic
has no geographic scale and illustrates area filtering, not simplification or repair.*

Convert the deviation to degrees using WGS84 meridional distance at a representative
latitude, then take the maximum with the collinear epsilon. Assemble surviving parts
before topology-preserving simplification, so neighboring parts cannot independently
drift into one another. If the result is invalid, apply `make_valid`. Derived measurements
are taken from the resulting cleaned geometry.

The conversion is a north/south degree approximation, not a proof of a uniform 22-meter
geodesic Hausdorff bound at every coordinate. The epsilon can dominate a custom smaller
deviation; part and hole rejection use degree² rather than physical area. Repair can
alter geometry structure. These are rendering policies, not a guarantee of unchanged
source acreage or exact survey boundaries.

## Worked examples and boundaries

A perimeter with 99.5% inside and 0.5% outside crosses if the outside area is 600 acres,
because the absolute threshold independently qualifies it. A tiny outside sliver below
both thresholds does not. A wholly outside footprint has no inside area and cannot be
crossing regardless of its size. A Nevada-origin identifier on an interior California
footprint supplies an identifier flag, while geometry still selects inside.

Two overlapping outside parts of 400 square meters each with a 200-square-meter overlap
have outside area 600, not 800. Summing part areas breaks the absolute signal, even though
the extreme outside fraction remains one. For size rejection, measured 20 acres versus
computed 100 acres passes at equality; measured 19 acres fails. Measured 50 acres versus
incident size 1,000 acres stays eligible under the stricter incident-size collapse check.

Cleaning each adjacent polygon independently can change their relationship; assembly
before simplification preserves the intended topology contract. Conversely, retaining all
microscopic holes keeps rendering slits that this policy is designed to remove.

## Costs and limitations

For N observations with B WKB bytes, deduplication hashes O(B) bytes and stores distinct
keys. Projection is linear in coordinates. Union, intersection, symmetric difference,
and repair depend on vertex and intersection counts and can dominate runtime; no constant
bound per polygon is assumed. Freshest-source scans are O(N). Size measurement scans
rings. Cleaning visits every part/hole and invokes GEOS simplification/repair, with memory
proportional to input and generated geometry. The same-sided shortcut avoids union only
when its scalar result is exact; outside area still requires union.

## Implementation and verification

Owners: [border classification](../../src/peri_scribe/perimeters/border_classification.py),
[signals](../../src/peri_scribe/perimeters/signals.py),
[CRS/configuration](../../src/peri_scribe/perimeters/classification_data.py),
[size filtering](../../src/peri_scribe/perimeters/size_filtering.py), and
[cleaning](../../src/peri_scribe/perimeters/cleaning.py).
Ordinary checks include [classification](../../tests/tests/standard/peri_scribe/perimeters/test_border_classification.py),
[signals](../../tests/tests/standard/peri_scribe/perimeters/test_signals.py),
[cleaning](../../tests/tests/standard/peri_scribe/perimeters/test_cleaning.py),
[size filtering](../../tests/tests/standard/peri_scribe/perimeters/test_size_filtering.py),
and [cleaning properties](../../tests/tests/property_based/peri_scribe/perimeters/test_cleaning.py).

[Border and composition formal inventory](../../tests/formal/lean/perimeter_composition.md)
and [conformance](../../tests/formal/conformance/test_perimeter_composition.py) cover
signal precedence, one-sided optimization, freshest extents, and final rejection using
finite exact geometry abstractions and real projection examples. These do not prove GEOS,
PROJ, source truth, or equality at every floating-point threshold. Cleaning is a GEOS
rendering transformation with ordinary property/regression tests; there is no existing
formal cleaning model or new behavior introduced by documenting it. A future change to
its topological or numerical guarantee requires a fresh formal assessment.

# Progression colors, playback, and map icons

## Contracts and assessments

These presentation algorithms consume already prepared chronological growth rings.
They preserve the supplied ring order rather than sorting or reconstructing history.
Color selection requires finite nonnegative ring areas in compatible area units and
aware observation timestamps. Tour targets require a unique folder-occurrence ID and
one placemark for every supplied ring position. Icon inputs are valid RGB colors and
pixel-valued stroke dimensions. The geographic scope remains nationwide; time labels
use the project's existing `America/Los_Angeles` display convention.

| Behavior | History/state | Rules | Mathematics | Scale/representation | Failure/concurrency | Tier |
| --- | --- | --- | --- | --- | --- | --- |
| Active growth window and colors | 1 | 2 | 2 | 1 | 0 | Involved: 6 |
| Tour visibility and timing | 2 | 2 | 1 | 2 | 0 | Involved: 7 |
| Antialiased diagonal icons | 1 | 2 | 2 | 1 | 0 | Involved: 6 |

For colors, local moving-window state supplies history score 1; threshold, asymmetric
tie selection, timestamp clamping, and short-span color range interact (rules 2).
The sliding-window correctness argument and temporal interpolation require composed
mathematical reasoning (2); the dated ring arrays are ordinary in-memory data (scale 1).

For tours, each reveal depends on ordered prior reveals (history 2); missing times,
duration compression, and the final hold interact (rules 2). Rate scaling is standard
arithmetic (mathematics 1). Every serialized step restates every target's visibility,
making output size quadratic in ring count (scale 2).

For icons, back-to-front stroke order is local state (1); outline/fill precedence and
coverage/opacity interact (rules 2). Projecting subpixels onto a finite segment and
recovering straight-alpha colors require geometry and numerical reasoning (2). The
fixed supersampled grid gives scale 1. None owns external persistence or concurrency;
the enclosing [output writer](output-serialization.md) owns those effects.

## The shortest window containing 98% of dated ring area

Discard undated rings for color selection. Let their remaining areas be `a_i`, total
area A, and threshold `T = 0.98A`. This uses each ring's own `area`, not its independently
certified incremental union area. The active window is a shortest consecutive run whose
sum reaches T. It can exclude small rings on either side without letting a long quiet
tail stretch the time-to-color mapping.

For each right endpoint, add its area to a running sum. Move the left endpoint forward
while at least one ring would remain and removing the old left ring would still meet T.
With nonnegative areas, every earlier left endpoint is at least as long; after trimming,
the selected left endpoint gives a shortest qualifying window ending here. Each endpoint
moves only forward, so examining these candidates finds a globally shortest run.

Equal-length candidates use this exact scan rule: replace the saved window only when
the **new right endpoint's area is greater than the saved window's left endpoint area**.
Equality retains the saved window. This is not a general maximum-total-area or
lexicographic endpoint comparison. The rule favors the larger newly retained boundary
in the common case where neighboring candidate windows compete.

For ring areas `[1,100,2]`, the total is 103 and T is 100.94. No single ring reaches T:

| Candidate window | Sum | Length | Scan decision |
| --- | --- | --- | --- |
| `[0,1]` | 101 ≥ 100.94 | Two rings | Save this qualifying window; its left boundary area is 1. |
| `[1,2]` | 102 ≥ 100.94 | Two rings | Replace the saved window because the new right boundary area 2 exceeds 1. |

The winning active window contains rings 1 and 2; ring 0 lies before it. With
`[1,60,1]`, T is 60.76; the two qualifying two-ring windows tie on their compared
boundary areas, so `[0,1]` remains selected.

## Time-to-color mapping

The stored 256-entry Turbo table is trimmed by 16 entries at each end, leaving 224
entries. `turbo_at` linearly interpolates neighboring RGB entries and clamps requests
outside the ramp. If k rings lie in the active window, its coolest fraction is
`c = max(0, (10-k)/9)`: one active ring is entirely hot, while ten or more use the whole
trimmed ramp. For an in-window timestamp t, with endpoints t0 and t1, the ramp fraction
is `c + (t-t0)/(t1-t0) × (1-c)`.

Rings before the window use c; rings after it use 1. If t0 equals t1, every in-window
ring is hot, while preceding rings still use c. No dated rings yields an empty color
sequence. Nonnegative all-zero areas select the first ring as the active singleton,
making every dated ring hot. Negative or nonfinite areas violate the sliding-window
assumptions; an unattainable manually supplied threshold leaves the helper's initial
whole-span fallback rather than proving that the threshold was satisfied.

The `[1,100,2]` example uses `c = 8/9`: the excluded early ring and the first active
ring have the same color; the final active ring is hot. For a three-ring active span
at times 0, 6, and 24 hours, `c = 7/9`, and the middle fraction is
`7/9 + (1/4)(2/9) = 5/6`. Equal spacing by ring index would produce a different color.
Colors therefore encode relative observed time within significant growth, not acreage
magnitude or absolute calendar date. Neither the 98% policy nor Turbo is a claim of
perceptual optimality.

## Playback visibility and timing

For each ring position i, the target is `progression-ring-<folder_id>-<i>`.
Step i explicitly shows all targets through i and hides every later target. Restating
the complete visibility vector makes a step replayable without relying on the viewer's
previous visibility state. Unique folder occurrences keep repeated fire views separate.
Folder listing order does not determine reveal order.

Let D be the span in days between first and last known observations. The rate is one
second per day for D ≤ 5, otherwise `5/D` seconds per day. Each adjacent pair waits its
day gap multiplied by this rate; a missing endpoint makes that pair's wait zero. After
the last reveal, the implementation holds for **one second** (`FINAL_TOUR_WAIT`). Thus
a fully dated ten-day sequence spends five seconds advancing plus a one-second final
hold. For observations on days 0, 2, and 10, the rate is `5/10 = 0.5` seconds per day:

| Reveal | Observation day | Ring 0 | Ring 1 | Ring 2 | Wait after reveal |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | On | Off | Off | 1 second, then reveal ring 1. |
| 1 | 2 | On | On | Off | 4 seconds, then reveal ring 2. |
| 2 | 10 | On | On | On | 1-second final hold. |

Each row is a complete visibility vector: earlier rings remain visible and every future
ring is explicitly hidden. The waits are `[1,4,1]` seconds.

Missing times are not bridged. For `[day 0, None, day 10]`, the rate is still 0.5, but
both adjacent gaps wait zero; only the final one-second hold remains. Equal timestamps
also have zero waits. A single ring gets its final hold; an empty sequence emits an
empty playlist. Inputs must be chronological: negative gaps are not clamped by these
helpers. The writer checks that target and wait counts match, but does not validate
chronology or recover a missing placemark target.

## Antialiased icons and straight-alpha reconstruction

Perimeter icons use a 16×16 canvas and 16×16 subpixel samples per output pixel. Each
diagonal segment runs from `(c-h,c+h)` to `(c+h,c-h)`. For sample `(x,y)`, its closest
segment parameter is `p = clamp((x-y)/2,-h,h)`; distance is measured to `(c+p,c-p)`.
Samples within radius 3 pixels become opaque black; samples within radius 2 become the
stroke color. Those radii produce a four-pixel colored stroke with a one-pixel outline
and round endpoints. Later strokes overwrite earlier strokes where they overlap.

![Subpixel coverage determines alpha without darkening the stored edge color](assets/progression-icon.svg)

The simplified 4×4 sample grid illustrates the same averaging used by the production
16×16 grid. Four covered red samples yield full red RGB and 25% opacity, not dark red
at 25% opacity. This distinction prevents a second darkening during compositing.

For C covered samples among S² samples, alpha is `255C/S²`, while straight RGB is the
sum of sample RGB divided by C; an uncovered pixel remains all zeros. Covered black
outline samples contribute to C while adding zero RGB, so mixed border/fill pixels get
the appropriate darker color. Round channels to bytes, then emit filter-zero RGBA rows
with PNG header, zlib-compressed data, and CRC-protected chunks. The progression folder
icon instead samples 16 rows across the trimmed Turbo ramp, hottest row at the top.

## Costs and verification

Window sums, the 98% threshold, and timestamp ratios use the implementation's numerical
arithmetic without a comparison tolerance. Near-cutoff inputs can depend on rounding;
the nonnegative-sum argument above does not establish a universal binary64 error bound.

For n dated rings, active-window selection is O(n) time and O(1) auxiliary state; the
complete coloring operation retains O(n) dated inputs and outputs. Generic ramp sampling
is O(requested color count). Rate calculation is O(n); a tour contains n full n-target
visibility updates, so serialization is O(n²) target entries with O(n) transient state
per update. It is not linear merely because output is streamed.

Icon rasterization with L strokes, side P, and S samples per pixel side costs
O(LP²S²) time and O(P²S²) working arrays. P and S are both 16 in production. This is a
fixed-resolution coverage approximation, not exact area integration or color-managed
linear-light compositing. Rasterization does not change mapped geography.

Implementation: [colormap.py](../../src/peri_scribe/kml/colormap.py),
[tour.py](../../src/peri_scribe/kml/tour.py),
[KML tour writer](../../src/kml_io/tour.py), and
[icons.py](../../src/peri_scribe/kml/icons.py). Ordinary tests cover
[colors](../../tests/tests/standard/peri_scribe/kml/test_colormap.py),
[timing](../../tests/tests/standard/peri_scribe/kml/test_tour.py),
[visibility serialization](../../tests/tests/standard/kml_io/test_tour.py), and
[icon pixels](../../tests/tests/standard/peri_scribe/kml/test_icons.py).
Generated tests cover [shortest windows and color invariance](../../tests/tests/property_based/peri_scribe/kml/test_colormap.py),
[tour timing](../../tests/tests/property_based/peri_scribe/kml/test_tour.py), and
[raster properties](../../tests/tests/property_based/peri_scribe/kml/test_icons.py).

[OutputReferences](../../tests/formal/lean/output_references.md) proves unique complete
tour targets and cumulative reveal prefixes; its
[conformance bridge](../../tests/formal/conformance/test_output_references.py) inspects
actual serialized tours. [DifferentialRows](../../tests/formal/lean/spatial_boundaries.md)
connects upstream visible ring selection with the presentation sequence. Those results
do not prove the 98% sliding-window tie policy, interpolation, playback duration, raster
appearance, or Google Earth's playback implementation. These existing presentation-only
policies introduce no durable workflow; ordinary tests and the arguments above cover
the unmodeled presentation calculations in this documentation-only change.

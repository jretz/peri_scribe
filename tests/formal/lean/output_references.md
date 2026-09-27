# Ranked views and output reference integrity

`RankedViews.lean` and `OutputReferences.lean` cover score-to-fire association, ranked
selection, observation windows, and resource references. `OracleOutputs.lean` executes
the same definitions used by the proofs. Build with `mise formal-lean`; compare the
implementation and saved artifacts with `mise formal-conformance`.

## Ranked views and score ownership

The reference resolves each score against the complete showable fire collection.
Identifier matches take priority. Without an identifier match, the last same-name
fire in input order receives the score, matching the documented fallback contract.
This ambiguity is explicit: the proof does not establish that a name-only match is
the correct real-world incident. A score for an excluded identifier can fall back to
a same-name showable fire.

Scores are ordered by descending score and case-folded name, preserving input order
on ties. The first row resolving to each owner is retained before applying the output
limit. The proofs establish:

- Every selected owner is showable and has a complete supporting source score row.
- Identifier matching has priority over conflicting name matches.
- Owners are unique and the result respects the requested limit and ranked order.
- Each owner's retained score is at least every other score resolving to that owner.
- Top-fire owner selection equals the prefix of the associations used for displayed
  scores and explanations. Association retains the exact winning source row.

`presentation.score_association.associated_scores` supplies this relation to top and
notable views, prepared description notes, and report entries. The lower-level
`score_maps` and standalone single-fire lookup helpers remain available for callers
without a complete collection; they do not establish the full-collection association
contract by themselves. Report sections select from that complete collection before
location measurement and entry construction run over the union of selected fires.

Conformance exercises 480 configurations over three fires: all showable subsets,
distinct and repeated names, alias score rows, identifierless fallback, score ties,
opposing score orders, and three limits. Another 420 scenarios run real DataFrame
history preparation, descriptions, and `report_from_fires` with limits of 1, 2, and 50,
comparing selected score and explanation provenance with the Lean association output.
An additional case places 60 unshowable scores before an eligible fire, ensuring that
exclusion happens before the 50-fire limit.

The checks exposed two ranking defects. Duplicate aliases could consume all 50 slots
before another eligible fire appeared. A fire could also be ranked using its highest
alias score while its report displayed the lexically first alias's lower score.
Ordinary regressions failed before the fixes. Ranking now deduplicates first, and
the shared full-collection association supplies ranking and displayed evidence.

## Observation windows and growth

Window selection includes both the cutoff and the reference instant, and excludes
future observations. The latest-selection proof establishes source membership,
nonfuture time, and maximal time among all eligible measurements. Appending a future
measurement cannot change the selected value. The growth definition compares the
latest eligible measurement with the latest measurement at the cutoff; no baseline
means zero acreage and an undefined percentage. Percentage eligibility requires a
strictly positive baseline and uses an exact cross-multiplied threshold comparison.

The bridge checks 751 histories with missing history, zero baselines, corrections,
equal timestamps, reordered input, cutoff boundaries, and future measurements. Both
acreage and percentage admission flags come from the executable oracle. Twelve
additional scenarios check discovery and personnel windows through the actual recent
view selectors, including zero personnel and both inclusive boundaries.

The Lean ranking key uses natural-number name tokens preserving the fixture's
case-folded order and equality. Time is integral elapsed seconds and area is integral
acres. Arbitrary Unicode collation, floating-point rounding, geometric measurement,
custom thresholds, and source-clock truth are not proved. The complete new-notable
signal and percentile policy is covered by the separate [policy details](policy_details.md)
extension. Arbitrary combinations of all output views remain outside these theorems.

## Resource allocation and complete artifacts

The resource model preserves equality after filename normalization by assigning a
token to each distinct candidate string. It proves that allocation picks an offered,
unused candidate, preserves a unique registry, and succeeds when a distinct candidate
list is longer than the used registry. A resource carries both name and owner. The
closure predicate requires the exact pair; an unrelated owner's same-name resource
cannot satisfy it when names are unique.

Ring targets are pairs of document folder occurrence and ring position. The model
proves the complete target range, unique targets, and disjointness between folder
occurrences. A repeated fire in another view has a different folder occurrence.
Each reveal step retains earlier rings, and the final step reveals every target.

The filename bridge checks 60 ordered triples of case, punctuation, empty-name, and
suffix collisions, giving 180 allocations against the executable reference. Complete
artifact checks then:

- Render real SVG chart bytes for four distinct owners with colliding filename bases.
- Write actual ZIP archives through `kml_io.kmz.write_kmz` and the full
  `kml.builder.write_fire_kml`, preserving styles, balloons, icons, views, and tours.
- Reopen both archives, compare every image payload byte-for-byte, check unique archive
  members and XML IDs, resolve local style and icon references, and bind balloon image
  references to the owner of the exact serialized point coordinates.
- Compare each tour's complete target set and every serialized visibility update with
  Lean output, including repeated fire views and an undated perimeter fallback.

The two archives reverse the per-fire ring counts zero through three. The explicit
external Google point-icon URL is checked against `styles.POINT_ICON_URL`; its remote
availability is outside local archive closure. Geographic input acquisition,
`create_kmz`'s publication/journal transaction, and renderer appearance are covered
elsewhere or excluded here. The artifact adapter assembles the plot/icon registry
before calling the production archive/document writers.

## Markdown detail links

Names and normalized heading slugs are not unique identities. Actual saved Markdown
reports are rendered by `markdown_it`, and the generated HTML is parsed to inspect
the real IDs, links, and owning detail tables. Five artifacts include repeated names,
punctuation collisions, preexisting numeric suffixes, and names matching report
section headings, repeated hyphens, Unicode, and inline Markdown punctuation.

The initial regression demonstrated links resolving to another fire or a section.
Details now receive explicit `fire-detail:<position>` anchors, outside automatic
heading-slug namespaces. Every summary reference uses the same allocated owner
position, independent of heading normalization. The adapter compares these positions
with the proved unique index range and checks each actual linked table's identifier.
Two additional artifacts load through the terminal monitor's actual `ReportViewer`.
The conformance adapter obtains the unique owner positions and reference closure from
the Lean oracle, follows every generated summary target through `ReportDocument`, and
checks that the selected heading's rendered detail table contains only its owner's
identifier. These cases include repeated names, heading and punctuation collisions,
and escaped anchor lookalikes in source names. Ordinary regressions cover document
replacement and inherited heading-link behavior.

Browser Markdown rendering must preserve explicit HTML anchors. The terminal monitor
recognizes report anchors at their parsed source positions before navigating to the
following detail heading. General sanitizers, arbitrary embedded source HTML, visual
layout, and third-party renderer correctness remain outside the unbounded proofs.

The unbounded proofs concern the declared list/integer/resource domains. Bounded
Python and artifact conformance connects those definitions to current behavior; it
does not prove arbitrary Python executions or external renderers refine the model.

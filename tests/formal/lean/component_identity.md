# Anonymous source components

`ComponentIdentity.lean` has 24 theorems covering the source-component boundary that
supplies distinct report identities to history transfer. `OracleComponentIdentity.lean`
executes the proved definitions through `oracleComponentIdentity`. Run `mise
formal-lean` and `mise formal-conformance` to build and check them.

## Guarantees

A nonempty component chooses its least immutable source-row occurrence. The chosen
anchor belongs to the component and is no larger than any member. Permuting observations
preserves the anchor; disjoint components cannot choose the same occurrence. Appending
occurrences at or after a retained anchor preserves it. A merge chooses the smaller old
anchor, and a split containing the old anchor retains that identity.

Every row occurrence also supplies an internal alias. A retained former component anchor
therefore remains claimable after a merge or identifier enrichment. These aliases remain
separate from source-issued identifiers and never participate in source identifier
grouping. Durable history ownership uses the existing latest-mapped-observation policy
from `IdentityTransfer`; the component model supplies its identities and alias inputs.

Tagged report keys prefer an external identifier, then an anonymous component, then a
legacy name fallback. Identical text in different namespaces cannot identify the same
fire. Exact component history filtering retains the original row order, selects
precisely the owned rows, and prevents one component from drawing another component's
observations.

Scoring's string keys escape external identifiers beginning with `id:`, `name:`, or
`component:`. Other identifiers keep their spelling; anonymous components and legacy
names use their corresponding prefixes. The prefix-token model proves that decoding
reverses encoding, hence the encoding is injective and neither names nor components can
collide with external IDs. Conformance checks the real string separators and nested
escapes.

## Application and conformance

The application carries `component_id` through `Fire`, the fire index, each full and
differential history row, score entries, `FireSummary`, map geometry, report details,
and the checkpoint/log identity. The index and summary also carry `component_aliases`;
the whole alias set is not repeated in every geography row. Source identifiers and
aliases retain their external meaning. Source, per-fire, and complete-frame dependency
keys invalidate derived products when the component algorithm or identity fields change.

`helpers/component_identity.py` supplies four conformance tests:

- **194 source catalogues:** all eight identifier graphs on three records, near and
  distant same-name geometry, present and missing object IDs, and all six row orders,
  plus absent/empty-geometry duplicate occurrences. The separate `Grouping` oracle
  supplies connectivity; `ComponentIdentity` supplies each anchor and complete aliases.
- **234 scoring-key encodings:** external, component, and name namespaces with reserved
  prefixes, nested escaping, empty strings, non-ASCII text, and literal separators.
  Another **eight identity cases** check report-key priority and checkpoint aliases.
- **14 real publication rounds:** anonymous California/Alaska namesakes, reversed input,
  identifier enrichment, merged identities, corrected grouping, and reversals. Full and
  differential GeoPackages are written and read, then actual qualification, history
  selection, score association, reports, and the map geometry adapter run. Only plot
  construction and image rendering are replaced.
- Those same map geometry objects enter the existing `IdentityTransfer` oracle bridge
  for real update preparation, persisted checkpoints, monthly JSONL, and viewer JSON.
  The bridge checks complete original/inherited evidence, learned lineage, ownership,
  novelty, preserved journal bytes, input-order independence, frozen-write retries, and
  recomputation after acknowledgment.

Ordinary regressions failed before the implementation: two separately grouped anonymous
fires produced one prepared history, and both summaries drew both fires' polygons.
Further regressions exposed the preexisting collision between a literal external ID
`name:Canyon` and the anonymous name `Canyon`. The tests also check numeric serial
ordering across 999999/1000000, duplicate rows without object IDs, exact point/report
selection, excluded namesake baselines, and persisted component score metadata.

## Boundaries

These are unbounded finite-list/opaque-identity proofs and bounded Python conformance,
not a proof that Python implements every Lean operation for all inputs. The wire proof
abstracts reserved textual prefixes as tokens; the real prefix spelling is checked by
conformance. Geometry, source truth, external identifier normalization, and SHA-256
collision resistance are separate assumptions or contracts.

Anchors use feed name, numeric snapshot serial, immutable snapshot filename, and source
object ID. Valid feed snapshots have unique object IDs and canonical snapshot placement.
When an object ID is missing, the anchor uses the complete normalized record, geometry,
and attributes. Indistinguishable duplicate occurrences receive distinct ordinals; their
set of keys is stable, but there is no meaningful persistent correspondence between
indistinguishable copies. Legacy unparseable filenames use a fallback ordering.

Retaining the least source occurrence stabilizes ordinary same-feed snapshot extension.
Introducing an earlier source anchor or removing the selected anchor can change the
component key; retained aliases and mapping/source evidence handle continuity. Alias
sets grow with retained source occurrences. Exact component ownership does not establish
a real-world identity relationship between observations connected by the grouping
policy.

The correction scenarios provide changed source catalogues explicitly. They do not claim
that appending a new snapshot breaks identifier connections still present in retained
history. Merged histories remain jointly claimable through saved lineage; a later split
uses the existing ownership arbitration and does not reconstruct a previous partition.

Legacy files and directly constructed summaries without component metadata retain their
name fallback and its documented ambiguity. Normal geography generation rebuilds changed
code/dependency generations; adding defaults to the schema does not recover missing
component provenance from a legacy name-only row by itself.

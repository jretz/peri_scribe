# Publication baseline ownership

`PeriScribe/PublicationBaseline.lean` contains 27 theorems about the complete collection
processed by `publication.published_fires(collection, perimeters, index)`.
`OraclePublicationBaseline.lean` builds `oraclePublicationBaseline` from the same
definitions. This extends the single-row raw-source join in [Publication evidence].

## Complete row-order contract

Every displayed row must match exactly one raw mapping on its source file and object
identifier. A missing or duplicate match anywhere rejects the complete collection,
including rows excluded from the output index. Every resolved row has an original input
witness. The complete baseline theorem connects the final retained source to a uniquely
matching raw mapping from an actual displayed input row.

Owners are tagged canonical identifiers or anonymous names. For each owner, the fold
retains exactly the union of its rows' identifiers, displayed aliases, and raw-source
identifiers. Aliases are monotone across appended rows and cannot leak between owners.
Result owners are unique and correspond exactly to owners present in resolved rows.

The source and display name come from the last row for that owner in supplied row order.
The fold agrees with an independent `getLast?` reference, and later unrelated rows do
not change that source. Concatenating row streams agrees with continuing the earlier
fold. These guarantees do not assume that source timestamps increase: the publication
function preserves the displayed history's order rather than choosing the largest raw
timestamp or source serial.

Index visibility is computed from actual index entries, not a supplied Boolean. A fire
is included exactly when its accumulated aliases intersect an index entry's identifier
or aliases, or when an anonymous owner has the same name as an anonymous index entry.
Every inclusion has an index witness. Identified owners cannot qualify by name alone.
Alias accumulation preserves visibility, even when a final row lacks an earlier row's
matching alias. Excluded owners retain their identity evidence but have no area
baseline. A displayed baseline is always the final raw source for its owner.

## Implementation connection

`conformance/test_publication_baseline.py` checks 4,473 complete collection results
against the compiled oracle. It covers every sequence of zero through three rows drawn
from eight cases, permutations of four interleaved rows, and missing or duplicate source
associations in several stream positions. Each stream is crossed with seven indexes:
empty, direct-identifier membership, alias membership, anonymous-name membership,
identified namesakes, anonymous entries carrying aliases, and overlapping index aliases.

Cases include repeated owners with changed names and sources, aliases introduced by both
displayed and raw rows, anonymous and identified owners sharing names, absent object
identifiers, and excluded owners. Derived identifiers use braces, case, and whitespace
variants, displayed alias fields repeat tokens, and DataFrame row labels repeat. The
source inventory's dictionary order differs from row order. Source timestamps and
serials deliberately run opposite to source identities. Results compare full ordered
owner/name/source/alias vectors and the complete selected immutable raw mapping,
including area and provenance. No Python ownership fold supplies expected results.

`conformance/test_publication_baseline_output.py` adds 17 real output-path executions
from nine curated scenarios and applicable row/index reversals. These contain 29 derived
rows and 15 included groups. Actual `prepare_histories`, `area_qualified_index`, and
`fire_summaries` produce the visible index and exact perimeter source references before
the complete `published_fires` result is compared with Lean. Cases include aliases
joining two derived owners into one summary, anonymous/identified namesakes, a missing
object ID, small excluded fires, and historical area qualification retained after a
downward correction. Raw source areas deliberately differ from derived qualifying areas.

The output bridge also calls real `commit` and `read_publication`: the saved baseline
retains the oracle-checked owners, aliases, raw mappings, and output file stamp.
Its output fixture serializes actual summary names as JSON, so this check establishes
the checkpoint binding to those visible identities without claiming KML byte generation
or rendering. The history and selection path has no mocked selectors.

## Proof boundaries

The proofs quantify over arbitrary finite streams, source inventories, alias lists, and
indexes. Geometry, names, normalized identifiers, file paths, and mapping records are
opaque identities. The source join includes an optional object identifier, faithfully
representing the existing policy that one uniquely matching missing object ID is usable.
Lexical normalization and numeric object-ID decoding are implementation boundaries;
conformance exercises their representative raw forms.

The inclusion relation is existential and deliberately does not prove that an index
alias belongs to only one entry. Overlapping index aliases can make several owners
visible. Ensuring that grouping and index construction produce the intended identities
is a separate contract. This model and its existing cases describe legacy rows without
component metadata, where repeated anonymous names share one owner. Source-derived rows
carry exact internal components; [ComponentIdentity](component_identity.md) covers that
stronger boundary, with an ordinary regression checking excluded namesake baselines.

Alias list order and duplicate elimination are represented extensionally; the bridge
also checks the production sorted tuple. Result dictionary order follows first owner
appearance in the executable model and is compared in every conformance case. The
unbounded owner theorems establish uniqueness and membership; they do not assert that
changing input order leaves dictionary order or final source unchanged.

The model verifies baseline ownership, source evidence, and the explicit index relation.
It does not prove chronological preparation of the input frame, geodesic measurements,
area eligibility, KML serialization, or checkpoint transaction durability. Those have
separate contracts and implementation tests. No production defect or behavior change was
needed for this extension.

[Publication evidence]: evidence.md

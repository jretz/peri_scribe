# Source-change fingerprints

`PeriScribe/SourceDigest.lean` checks the structured identities used by
`sources.digests.dataframe_digest`. Its 21 theorems cover field framing, schema identity,
and canonical row bags before cryptographic hashing. `oracleSourceDigest` executes those
same definitions for implementation conformance.

## Contract

Normalized attribute fragments and geometry bytes are separate fields. Literal zero
bytes are escaped as `00 01`; `00 00` terminates each field. The parser recovers a field
and an arbitrary following suffix. Consequently, encoding a list of fields is injective:
source content cannot turn part of one attribute into another attribute's boundary.
Empty payloads and empty field lists remain distinct.

Schema identity includes sorted attribute names and the coordinate reference. It remains
present for empty frames. Canonical row ordering ignores source row order while retaining
each row's multiplicity. The proofs establish that canonical row lists agree exactly when
the input lists are permutations, including repeated rows, and that schema changes cannot
be hidden by an empty row list. Missing-value normalization happens before framing; None,
pandas NA and NaT, and floating NaN intentionally share one source-comparison fragment.

The production fingerprint hashes each framed row and the framed schema separately,
then frames the schema digest and sorted row digests for the final hash. Equal fixed-width
hash bytes sort in the same order as their big-endian natural-number representation.
Hash collision resistance remains an assumption. These proofs do not establish SHA-256
injectivity.

## Implementation correspondence

`helpers/source_digest.py` declares source values and their normalized byte fragments
independently of the production normalizer. `conformance/test_source_digest.py` checks:

- 1,898 field sequences, including all individual byte values, embedded zero bytes,
  empty fields, and exhaustive short delimiter-containing strings, against Lean's exact
  framing output.
- 24 scalar representations, including missing aliases, bool/integer/float distinctions,
  signed zero, binary data, dates, UTC timestamps, and Unicode.
- 114 concrete dataframes against hash inputs supplied by the executable Lean framing
  and canonical-order definitions, plus all 6,441 pairwise semantic-equivalence decisions.
  Cases include column permutations, renamed fields, row permutations, duplicate rows,
  empty frames, and absent or distinct coordinate references.
- Actual GeoPackage writes, reads, and snapshot comparisons, followed by a real
  `fetch_arcgis_source` publication/reuse sequence with only network retrieval replaced.

Ordinary regressions in `test_digests_framing.py` failed before the fix for ambiguous
field boundaries, renamed fields, empty schemas, and differing coordinate references.
For example, `("a", "sb")` and `("as", "b")` previously supplied the same unframed bytes.
Custom coordinate references also retain their meaning without an authority identifier.

## Boundaries

The unbounded proofs concern exact normalized fields and symbolic row-hash values, with
finite conformance connecting them to Python, pandas, GeoPackage, and SHA-256. They do not
prove external source truth or arbitrary Python execution. Coordinate references use
their authority identity when available and their WKT otherwise. Column dtypes, DataFrame
index labels, active geometry-column labels, and row/column order are intentionally not
source-change evidence; attribute names, normalized values, CRS, geometry bytes, and row
multiplicity are.

Source comparison keeps its existing scalar normalization policy. Arbitrary unsupported
Python objects use a repr fallback; this does not promise injectivity over all possible
Python object types. Geometry comparison retains exact WKB rather than topological
equivalence. Cryptographic collisions, library serialization, timestamp normalization,
and correctness of CRS authority resolution are outside the mathematical proof.

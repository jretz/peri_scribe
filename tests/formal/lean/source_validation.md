# Sound validation of complete source coverage

`PeriScribe/SourceValidation.lean` contains 16 checked theorem declarations, and
`oracleSourceValidation` evaluates their definitions. The implementation owners are
`sources.validation.{validate_feed,feature_contents,feature_contents_equal,
duplicate_object_ids,FeedValidationResult.has_problems}`. The pipeline logs the new
duplicate-ID and coordinate-reference diagnostics alongside missing content.

## Contract and proofs

A successful comparison establishes that every complete-snapshot row has a stored
witness with the same OBJECTID, normalized attributes for every complete attribute
column, and topologically equivalent geometry under the same known CRS. Both snapshots
must have unique OBJECTIDs. Extra stored features and columns are permitted, but even an
otherwise irrelevant stored duplicate makes that snapshot ambiguous.

The executable specification uses an indexed lookup. An independent relational contract
requires matching witnesses for all complete rows without using that lookup. The main
equivalence theorem proves soundness and completeness of the indexed algorithm against
the relational contract. Supporting proofs establish that a unique key retains its
entire row, all required fields agree, known CRS values agree, duplicate keys cannot
succeed, and row permutations preserve success. Valid frames cover themselves, and
additional stored rows or columns preserve coverage when IDs remain unique and the CRS
is unchanged.

Unknown CRS is insufficient even when both snapshots omit it or contain no rows. A
different CRS is a problem even when the stored numeric coordinates match exactly.
Validation does not reproject coordinates: its job is to compare snapshots of the same
source and detect incompatible spatial interpretation.

## Executable conformance and regressions

The bridge compares every public result field with the compiled oracle across 3,249
pairs of real GeoDataFrames. The 57-frame catalogue varies empty schemas, missing or
extra columns, row order, absent features, duplicate rows with equal or conflicting
contents, known and missing CRSs, normalized missing values, subsecond timestamps,
numeric representations, absent/empty geometry, distinct points, polygon wrappers, and
reversed rings. Another 114 comparisons cover absent stores and stores lacking OBJECTID.
Oracle inputs contain independently declared scalar and shape equality classes; the
adapter does not call production normalization or comparison to derive expectations.

Nine ordinary regressions were confirmed failing before the fix: incompatible or
unknown CRS and duplicate IDs could yield a clean report, including a conflicting first
row silently overwritten by a matching final row. These regressions remain in the
standard test tree. A duplicate is reported even when its contents agree; a shared
duplicate ID is also mismatched because no unique stored correspondence exists.

The oracle protocol is `validate|CRS|columns|rows|CRS|columns|rows`. CRS is a natural
equality token or `n`; columns are space-delimited tokens; rows are space-delimited
`OBJECTID,shape,column,value,...` records. Its response includes success, CRS mismatch,
then length-prefixed missing IDs, mismatched IDs, missing columns, complete duplicate
IDs, and stored duplicate IDs.

## Assumptions and limits

The model accepts arbitrary finite lists with unbounded natural identity tokens. Tokens
abstract normalized integer OBJECTIDs, column labels, CRS equivalence, normalized
attribute equality, and topological geometry equality. Source ingestion supplies usable
OBJECTIDs and unique column labels; the complete frame must carry its OBJECTID column.
The bridge exercises actual pandas, pyproj, and GEOS behavior for the stated fixtures,
but does not prove those libraries, geometric robustness, raw feed truth, or all possible
attribute types. Missing geometry and empty geometry have distinct equality classes.
Attribute normalization deliberately follows the source comparison contract, including
whole-second timestamp precision. The validation command's locking, complete-snapshot
collection, and retained diagnostic artifacts have separate protocol checks.

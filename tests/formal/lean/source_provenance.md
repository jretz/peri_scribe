# Exact source provenance reuse

[`SourceProvenance.lean`](PeriScribe/SourceProvenance.lean) checks the memo and current
dependency-construction refinements before production changes. Its six theorems retain
the complete contracts with these explicit boundaries:

- A memo entry equals the pure derivation for its complete key. The key identifies both
  the lexical directory and source path. Lookup therefore equals fresh derivation.
- Remembering that result preserves the invariant. Executing an arbitrary ordered
  query history equals the independent complete map, including repeated keys.
- Starting from an empty memo satisfies that invariant.
- For individually validated typed rows, checking unique references and constructing
  the canonical reverse map once equals applying the full aggregate validator to those
  same rows and that reverse map. The canonical constructor remains an explicit
  parameter; the theorem does not prove its incidence policy independently.
- An empty changed set has an empty affected closure under the existing retained-index
  path definition, so adjacency construction can be omitted in that case.

The Python memo is an explicit `SourcePaths` object retained by one source read and its
groups. It contains lexical strings, with no filesystem reads, checksums, receipt
eligibility, process ownership or external publication. It introduces no new temporal
protocol. Callers treat its dictionary as read-only. Exact stock immutable Path inputs
use it; custom source or directory subclasses retain fresh `relative_to` calls. Ordinary
tests establish that concrete boundary, lexical errors, separate owners and unchanged
sorted duplicate output paths. Retaining a read explicitly also retains its memo; there
is no global cache or copied-context lifetime to expire.

The executable presentation-flow `source-path` command runs the same generic memo trace
used in the proof. Conformance assigns exact lexical results to symbolic tokens and
compares 518 histories of length zero through three over six complete root/path keys
in both POSIX and Windows cohorts, with Unicode, an embedded zero, parent components,
case variants, distinct roots and repeated keys. Memo keys retain exact type and string;
Windows Path equality alone would incorrectly alias differently spelled source paths.
The model assumes pure stable derivation; it does not prove pathlib internals. Output
sorting and evidence SHA-256 remain the existing independent policies.

The optimized current dependency producer creates strict `DependencyRow` models locally
and checks unique references before the validated canonical construction. Arbitrary
`index_from_rows` inputs and persisted `DependencyIndex.model_validate_json` data still
run full validation. Ordinary regressions require one reverse construction for current
metadata, another on JSON decoding, and rejection of duplicate and invalid current rows.
The existing 31,250 retained-inventory conformance histories cover the empty-seed change
alongside bridge additions, removals and corrections.

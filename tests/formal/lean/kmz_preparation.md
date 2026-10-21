# Compact KMZ evidence

`PeriScribe/KmzPreparation.lean` contains eight theorems for warm publication input
selection. `OracleKmzPreparation.lean` executes those definitions independently of the
Python adapters.

## Contract and owners

`peri_scribe.kml.prepared_inputs` prepares one map invocation from authenticated full
and differential geography generations. Complete reporting histories determine which
fires qualify. Repeated maps can retain only those complete qualified histories and
load source attributes at the latest selected row for each qualified fire. The
remaining geography, ordering, schema and row identities remain available.

The model separates three obligations:

- A reusable identity agrees on full geography, differential geography, the complete
  fire index, minimum qualifying area, area policy and runtime context. The first five
  inputs form `preparation_key`; the product store separately guards runtime context.
- Each nonempty ordered selection demands its last position. Projected evidence
  preserves the exact original value at every demanded position. Empty selections
  demand nothing. Overlapping selections can share a demanded value.
- Filtering histories preserves the complete original history exactly when its
  qualification predicate is true. The area policy that supplies that predicate has
  separate incident/area and numerical-policy coverage.

The concrete latest-row adapter uses `HistoryRowIndex.positions_for`, preserving exact
component selection, aliases, and legacy name selection. A GeoPackage feature ID is
not its zero-based row position; projection maps retained original feature IDs back to
their original positions rather than subtracting one.

## Proofs and implementation conformance

The identity theorem establishes equality of every dependency for a matching identity.
The demand and projection lemmas hold over arbitrary finite ordered position lists and
arbitrary value functions. Qualification is an exact filter retaining complete payloads;
the theorem does not replace the established acreage policy.

`tests/formal/helpers/kmz_preparation.py` connects the actual production functions to
the compiled oracle. It checks all short position selections and their pairs, including
empty, overlapping, repeated and nonmonotone lists. A concrete GeoPackage combines
component, alias, identified, anonymous and absent selections with nonconsecutive
feature IDs. Actual projected values are compared with the checked projection, while
other columns, geometry, row order and dtypes must match an ordinary full read.

The qualification bridge checks unknown, zero, below-threshold, exact-threshold and
larger historical areas while current area differs. The identity bridge stores one
complete product, changes each dependency independently, and compares actual key/store
hits with the oracle. An unchanged deep-copied index must continue to hit.

## Assumptions and limits

Dependency tokens model exact canonical identities. Their relation to SHA-256 requires
the existing no-collision assumption; the proof does not establish cryptographic
security. The original manifest must have been produced by the exact qualification
filter under its authenticated identity. Existing product-cache checksums, canonical
decoding, domain validation and malformed-cache fallback remain required.

The v2 transport compresses each canonical history independently with Zstandard. The
reader requires one complete frame, then validates the original history bytes through
the existing typed decoder and exact reserialization check. This lossless adapter
preserves the model's opaque complete payload. Compression framing tests reject
truncation and extra frames; the model does not prove the compression library.

The projection theorem assumes that every source-attribute consumer accesses only its
demanded latest row while complete prepared histories supply reporting decisions.
It does not justify dropping historical attributes for consumers that reconstruct
history, survey freshness or sparse fallbacks themselves. The adapter must retain or
fetch those attributes before such a consumer runs.

Generation authentication and row reads remain inside the existing year read lock.
The formal model does not prove GDAL/SQLite behavior, arbitrary Python refinement,
coordinate transformations, floating-point acreage comparisons or third-party data
truth. The existing geography-publication and product-cache transaction models govern
those unchanged persistence and lifetime boundaries.

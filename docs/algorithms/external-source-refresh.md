# External source refresh

External datasets use different refresh contracts. Cities support conditional HTTP
refresh, evacuations replace a live layer, and static reference sources download when
missing or unusable. A complete replacement must be ready before its public path changes.

## Contract and assessment

Inputs are configured source URLs, saved files and metadata, and fetched data. Outputs
are usable local reference datasets or an explicit failure. The geographic scope is
the United States, including territories where supplied by the place dataset.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | HTTP validators and prior valid generations affect refresh decisions. |
| Rule interaction | 2 | Empty success, unchanged success, and failure have different meanings. |
| Mathematical reasoning | 1 | Content comparisons and source dispatch use established operations. |
| Scale and representation | 2 | Conversion uses chunks, archives, and source-specific schemas. |
| Failure and concurrency | 3 | Staged replacements and parallel conversions must retain usable generations. |

Total **10: complex**. Building conversion and worker cancellation are explained in
[building centroids](building-centroids.md) and [compact point storage](compact-point-storage.md).

## Conditional cities and live evacuations

An HTTP validator is useful only alongside a validated local generation. A successful
replacement publishes after conversion and validation, not when the response arrives.

1. Read and validate the local city database, including its schema, source identity,
   contents, and saved HTTP validators.
2. Send the conditional request, preferring the stored ETag and using Last-Modified
   when no ETag exists.
3. Interpret the response. A 304 keeps the validated file; without a usable prior
   generation it is an error. A 200 rebuilds a candidate database from the archive,
   selecting U.S. places and normalized state/territory codes and using point geometry
   for coordinates. Other outcomes fail the refresh.
4. Reopen and validate the staged database before replacing the published file.
   Refresh failure retains a valid prior generation and otherwise raises.

Metadata stores archive and canonical content checksums, source/schema versions, and
validators. Metadata-only changes need not change the canonical place-content digest.

Evacuations are queried in full, and source-specific normalization precedes content
comparison. The response determines whether stored zones remain:

| Response | Stored-layer result |
| --- | --- |
| Successful, unchanged content | Skip the write, including repeated empty content. |
| Successful, changed nonempty content | Write a staged GeoPackage and replace the previous file. |
| Successful, changed empty content | Write a valid empty layer and replace the previous file, clearing old zones. |
| Failed request | Keep a stored file when available; raise when none exists. No usable new response arrived, so do not infer that zones disappeared. |

Other configured sources can require nonempty results. Retaining a file after retrieval
failure does not certify that file's freshness.

## Static sources, alternatives, and limits

Static downloads and administrative borders validate usability before deciding to reuse.
Conversion finishes at a temporary path before replacement. Archive discovery, download,
extraction, and chunk conversion are separate adapters; only the completed result is
eligible for publication. Retaining every temporary download is unnecessary because
the published dataset is the reusable artifact.

The building archive index is parsed as HTML, not searched as raw text. A completed
`Download links` (or `Downloads links`) heading opens collection; the next heading or
GitHub heading wrapper closes it. Only completed anchors with nonempty labels and HTTP
URLs contribute state-to-archive entries. Text inside the page's embedded-data script
does not become a second table. The catalog then requires every configured state and
DC before download begins. A raw regular-expression search could accidentally accept
stale links from the embedded copy or a later section. Parsing is linear in page bytes
with storage proportional to collected labels and URLs; it assumes the documented HTML
heading structure. It does not infer omitted state links.

A city refresh that downloads valid content with a different ETag but identical places
can refresh metadata without rebuilding downstream outputs. In contrast, treating an
empty evacuation response as a download failure would retain zones the provider removed.
Overwriting a public database before validation would expose partial or invalid data.

Costs depend on download bytes, archive expansion, and feature count. Generic chunk
conversion bounds each processed chunk, not necessarily the complete workflow: city
archives and their extracted place collection can be held in memory. Building storage
has its own partition bounds. Atomic replacement protects individual files against
process interruption; this does not provide a transaction across sources or power-loss
durability. Network freshness remains conditional on the provider's responses.

## Implementation and verification

- [Cities](../../src/peri_scribe/sources/cities.py),
  [external source dispatch](../../src/peri_scribe/sources/external_sources.py),
  [download/conversion](../../src/peri_scribe/sources/downloading.py), and
  [administrative boundaries](../../src/peri_scribe/sources/administrative_boundaries.py).
- [Archive index parser](../../src/peri_scribe/sources/archives.py) and
  [archive tests](../../tests/tests/standard/peri_scribe/sources/test_archives.py).
- [ConditionalDownload](../../tests/formal/tla/ConditionalDownload.tla) and
  [StaticDownload](../../tests/formal/tla/StaticDownload.tla), with bounds in the
  [model inventory](../../tests/formal/tla/README.md).
- [Conditional refresh conformance](../../tests/formal/conformance/test_conditional_download.py),
  [static download conformance](../../tests/formal/conformance/test_static_download.py), and
  [building construction conformance](../../tests/formal/conformance/test_buildings_construction.py).

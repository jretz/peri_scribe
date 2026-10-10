# Literal text and streamed output publication

Source text must remain literal in reports and maps, while generated structure remains
explicit. Streaming KML and staging complete output files keep large documents practical
and prevent an interrupted writer from exposing a partial public document.

## Contract and assessment

Inputs are prepared fire facts, geometry, source strings, and explicitly generated
markup. Outputs are Markdown, XML/KML, JSON documents, or KMZ archives. Text encoding
preserves normalized content without adding document structure. Publication guarantees
apply separately to each destination file.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 1 | Writer envelopes and fragment reuse follow a local sequence. |
| Rule interaction | 2 | Source text, generated markup, and geometry channels have separate contracts. |
| Mathematical reasoning | 1 | Character encoding and coordinate serialization use direct transformations. |
| Scale and representation | 3 | Streaming and bounded retained fragments avoid full KML materialization. |
| Failure and concurrency | 2 | Completed staged documents replace public files after all writes close. |

Total **9: complex**. The durable multi-output protocol is covered separately by
[update journaling](update-journal.md) and [pipeline publication](pipeline-publication.md).

## Text channels

The same source characters can have structural meaning in Markdown and XML. Encoding
at each boundary keeps them in the intended text node or table cell:

1. **Normalize source characters.** Convert CRLF, CR, and NEXT LINE to LF. Preserve
   supported Unicode scalars in order; replace unsupported XML controls, surrogates,
   and excluded BMP noncharacters visibly.
2. **Encode for the destination.** Encode reserved characters as character references
   and boundary whitespace so Markdown cell trimming cannot silently remove it. Source
   `A | B` stays one Markdown table cell after parsing; `<name>` remains XML character
   data rather than an element.
3. **Add explicit generated structure.** `Markdown` and `CData` wrappers carry generated
   formatting; their interpolated source parts must already be encoded. Split embedded
   `]]>` terminators in generated CDATA descriptions so they cannot close the XML envelope.

## Geometry and publication

KML writers emit document, folder, placemark, and geometry envelopes to a stream.
Polygon serialization preserves exterior and interior rings; multipart geometries keep
their separate polygon boundaries. Coordinate formatting has a declared precision.
Tours reveal ordered placemark IDs through explicit visibility changes.

Boundary fragments are keyed by exact geometry bytes and coordinate precision.
Persistent fragments must decode canonically, match expected component count, and pass
the boundary grammar before entering XML. A writer-local least-recently-used cache
tracks retained bytes and evicts entries to its budget. The budget covers accounted
retained entries, not total Python memory or the temporary largest fragment.

Publication follows three steps:

1. **Open private staging beside the destination.** The previous public file remains
   readable throughout generation.
2. **Stream the complete document and resources.** KMZ serialization streams `doc.kml`
   into a staged ZIP archive and adds referenced images. Already compressed supported
   raster formats can be stored without recompression.
3. **Close all writers and the archive, then replace the public path.** A failure before
   replacement preserves the previous complete file, or leaves the destination absent
   on its first generation.

JSON, distribution HTML, and Markdown use their shared staged-document writer. Each
replacement publishes one complete file; other output files can still belong to a
different completed generation.

## Costs and limits

Text encoding is linear in characters. Geometry serialization is linear in emitted
vertices plus formatting and compression costs. Cache hits reuse boundary strings;
an oversized fragment may be created transiently without being retained. Image payloads
and prepared facts can still be held in memory, and KMZ writing disables ZIP64.

Escaping is specific to the output context: Markdown encoding is not a general HTML
template policy. Staged replacement depends on filesystem rename semantics and
cooperating writers. It does not make reports, KMZ, update JSON, and checkpoints one
transaction, and does not establish power-loss durability.

## Implementation and verification

- [Text encoding](../../src/document_text/encoding.py),
  [KML writer](../../src/kml_io/geometry.py),
  [fragment cache](../../src/kml_io/fragments.py),
  [KMZ publication](../../src/kml_io/kmz.py), and
  [document publication](../../src/peri_scribe/output.py).
- [Output text specification](../../tests/formal/lean/output_text.md),
  [output references](../../tests/formal/lean/output_references.md), and
  [DocumentPublication](../../tests/formal/tla/DocumentPublication.tla).
- [Text conformance](../../tests/formal/conformance/test_output_text.py),
  [reference conformance](../../tests/formal/conformance/test_output_references.py), and
  [document publication conformance](../../tests/formal/conformance/test_document_publication.py).
  Concrete parsers check rendered structure; ideal proofs do not establish arbitrary
  third-party renderer behavior.

# Source text and document structure

`PeriScribe/OutputText.lean` contains 28 theorems about normalization, text encoding,
generated markup, table framing, and CDATA envelopes. `OracleOutputText.lean` executes
the proved definitions. The implementation bridge compares both exact encodings and
parsed, saved Markdown and KMZ artifacts with that executable reference.

## Contract and implementation owners

Source text has a different role from generated document syntax. A source name such as
`North | South`, `[North](url)`, `<b>North</b>`, or `<![CDATA[North]]>` must retain its
literal content. It cannot create another cell, row, heading, link, XML element, or
balloon field. Generated report links and balloon HTML retain their intended structure.

The shared `document_text.encoding` module owns the normalization and the Markdown/XML
character-reference encoders. Its `Markdown` and `CData` types explicitly identify
generated markup; an ordinary string that resembles a marker receives no such status.

- `report.markdown.fire_heading`, `markdown_table_lines`, and `fire_table_section`
  encode source headings, cell values, and link labels. The table renderer accepts
  explicitly generated `Markdown` cells for links whose labels are already encoded.
- `kml_io.geometry.escape_text` encodes literal names and character data. Its separate
  `description_text` accepts generated `CData` only in the description channel.
- `kml.descriptions.description_html` normalizes and escapes interpolated field names,
  values, and image filenames before constructing a generated balloon. `kml.builder`
  explicitly marks the generated document attribution, and `kml.folders` carries these
  typed descriptions to the geometry writer.
- `fires.reuse.derivation_context` and `preparation.runtime_fingerprint` include the
  `document_text` package bytes. Encoding changes invalidate cached output preparation.
  The [cache dependency bridge](cache_dependencies.md) exercises this eighth package
  independently, alongside the other seven packages and native/runtime dependencies.

## Normalization and supported text

The portable text contract converts CRLF, CR, and U+0085 NEXT LINE to LF. Code points
outside the XML 1.0 character ranges become U+FFFD: unsupported C0 controls, surrogate
code points, and U+FFFE/U+FFFF. The model also defines this replacement for natural
numbers beyond Unicode's maximum, although Python strings cannot contain them.

All other supported code points retain their order and multiplicity. This includes
combining characters, supplementary-plane characters, NBSP, EM/thin spaces, and
U+2028/U+2029. Normalization is proved idempotent, emits only valid code points without
CR or NEXT LINE, and is the identity on already-supported text. The contract concerns
decoded text content, not whether a font or browser visually distinguishes it.

## Unbounded guarantees

The codec works over arbitrary finite lists of code points. Its atoms distinguish
literal characters from numeric references. The proofs establish decoding after
encoding, injectivity before normalization, concatenation preservation, and exclusion
of reserved characters from the emitted literal atoms. In particular, Markdown source
text emits no raw pipe, LF, or opening tag, and XML source text emits no raw opening
tag. Protecting boundary whitespace with references preserves content and introduces
no raw literals; actual renderer trimming behavior is checked by conformance.

The document model distinguishes source-text pieces from trusted-markup pieces.
For arbitrary piece lists, rendering preserves the exact markup skeleton and the
complete normalized source content in order, including repeated values. Cell and row
theorems establish fixed cell boundaries and retention of every declared cell. These
are theorems about the typed document model; they rely on references remaining data
when the wire representation is parsed. The bridge exercises that parser boundary.

CDATA uses a separate state machine that tracks trailing closing brackets. Before a
source `>` could finish `]]>`, it inserts a generated close/reopen token. The proofs
establish that no character sequence closes its current envelope and that decoding
all restarts preserves every character. Applied after normalization, this preserves
the exact normalized balloon body for arbitrary finite inputs. The Python replacement
implementation is compared with the independently structured state-machine oracle.

## Implementation conformance

`helpers/output_text.py` has 904 distinct source strings: controls and XML/Unicode
boundaries, individual and embedded Unicode whitespace, complete markup lookalikes,
repeated CDATA closers, literal character references, combining text, and all 512
length-three combinations of eight structural characters. No Python implementation
of the encoding policy supplies the expected results.

`conformance/test_output_text.py` checks each string in two ways:

- Compare normalization and exact Markdown, XML, and CDATA wire strings with the
  compiled oracle. Parse XML character data and CDATA, requiring exact normalized
  text and no injected child elements. Render the production Markdown table through
  `markdown_it` with its table extension, then require the exact two cells and content.
- Save a complete production Markdown report and a real KMZ. Parse the saved Markdown
  to check the heading, generated detail link, sole explicit anchor, every cell value,
  and the complete row/cell structure returned by Lean. Reopen the ZIP and parse its
  KML, checking document/folder/placemark names, the plain document description,
  generated balloon field labels and values, one placemark, exact archive members and
  image bytes, and the balloon's intended image reference without extra links.

The artifact check writes 904 report/archive pairs through the real report and archive
writers. Its KML adapter assembles a minimal real document, folder, placemark, style,
and balloon; the full fire collection builder and resource-reference composition have
their separate [artifact checks](output_references.md). No selector, storage, text
encoder, archive writer, or parser is replaced in this bridge.

Sixteen ordinary regression cases preserve the discovered source-text failures:
Markdown pipes/newlines could displace evidence, inline syntax changed names, Unicode
whitespace-only cells lost content, and literal CDATA markers or invalid controls
corrupted KML names. Each regression failed before its relevant fix. Property tests
also check literal CDATA markers and generated CDATA restart content independently
over supported XML strings. The deliberate-defect suite removes Markdown encoding and
requires the unchanged encoding conformance check to reject that production mutation.

## Executable reference and boundaries

`oracleOutputText` accepts `operation|codepoints`, with decimal natural numbers
separated by spaces. `normalize`, `markdown`, `xml`, and `cdata` return the resulting
code points. `rows` instead takes cell counts and returns the proved row/cell framing
tokens. This transport represents raw surrogates without asking an intermediate
Unicode decoder to interpret them.

The proofs do not verify the HTML/XML/Markdown libraries, their decimal-reference
parsers, ZIP implementation, or Python execution. Exact wire comparison and artifact
parsing provide finite conformance evidence for those connections. A caller must use
the generated-markup types only for markup whose source fields have been escaped in
their proper context. Arbitrary trusted markup is not proved safe by the type alone.

Markdown conformance uses CommonMark with tables and preserved explicit HTML anchors.
Other extensions, sanitizers, renderer-specific plugins, visual layout, source truth,
and arbitrary composed documents remain outside this contract. The normalization
policy is deliberate: exact preservation is claimed for supported text, and preservation
of the declared normalized value is claimed for other inputs.

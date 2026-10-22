# Prepared product representations

Prepared products preserve publication evidence while avoiding repeated conversions of
that evidence into temporary trees. The same cache values support source fingerprints,
prepared histories, descriptions, and KML fragments. None of these internal formats is
a published artifact: KMZ members, update documents, and reports retain their existing
representations.

## Contract and complexity

A cache value retains its declared type, exact scalar contents, original measurement
units, ordered container children, and schema. Float values keep their binary64 bits,
including signed zero and NaN payloads. NumPy scalars keep dtype and native bytes;
object-bearing and structured dtypes are rejected. Geometry identity means exact WKB
with SRID, not geometric equivalence. Timestamps retain ISO instant/offset, fold, and
pandas storage resolution. Enum reconstruction requires an explicit caller allowlist.

| Dimension | Score | Reason |
| --- | ---: | --- |
| History and state | 1 | Immutable payloads remain reusable only while mutation guards match. |
| Rule interaction | 2 | Domain scalar dispatch precedes builtin types; canonical validation rejects coercion and duplicate children. |
| Mathematical reasoning | 1 | Prefix framing and SHA-256 identities use standard algorithms with explicit boundaries. |
| Scale and representation | 3 | Direct binary output, shared row views, and compressed storage avoid intermediate representations. |
| Failure and concurrency | 2 | SQLite transactions and optional decoding failures must preserve cache-miss correctness. |

The total is 9, a complex algorithm. Published evidence makes exact representation
and implementation conformance essential even though the storage is disposable.

## Binary values and complete identities

The binary value starts with `PSCV` and version byte 2. Each node has a one-byte type
tag and an unsigned four-byte big-endian payload length. Leaf payloads contain exact
bytes. Composite values contain complete child nodes within that byte boundary. The
writer appends children directly into one buffer and fills in each enclosing length
when it finishes; it creates no tagged JSON tree and does not hex-encode byte payloads.

| Value | Node contents |
| --- | --- |
| Missing sentinel | Empty payload with a distinct sentinel tag |
| Boolean, integer, float, string, bytes | One boolean byte, decimal integer text, eight float bytes, UTF-8, or raw bytes |
| Tuple or list | Children in their original order, with distinct container tags |
| Dictionary | Alternating keys and values, preserving insertion order |
| Frozen set | Complete child encodings sorted lexicographically |
| Quantity | Typed magnitude followed by the original unit string |
| Enum | Qualified allowlisted class name followed by its typed value |
| NumPy scalar | Dtype string followed by its raw scalar bytes |

The reader accepts exactly one root. It validates node boundaries, reconstructs only
declared types, and requires re-encoding to equal the complete original bytes. This
last check rejects noncanonical numbers, extra fields, duplicate mapping keys or set
members, and scalar coercions. Unsupported versions miss safely; source changes also
change the enclosing runtime fingerprint, so incompatible typed payloads cannot become
warm hits under the normal publication context.

Source keys retain the complete ordered schema and selected row digests. Their preimage
starts with a distinct format/version prefix, then the length and bytes of the typed
identity and the number of source layers. Each layer contributes a length-framed schema,
its selected-row count, and every length-framed row digest in selection order. Explicit
lengths distinguish changing a field from moving a boundary. The key writer streams
those pieces into SHA-256 instead of constructing another typed tree of byte strings.
Hash collision resistance remains an assumption, not a theorem about SHA-256.

For example, selecting rows `(2, 5)` differs from `(5, 2)` and from `(2, 2, 5)`.
Selecting no rows still includes the schema, so changing units, dtype, geometry column,
or CRS invalidates an empty selection. Duplicate column names remain positional.

## Sharing prepared evidence

A completed qualified history retains its canonical immutable payload alongside its
digest and mutation guards in the execution scope. Aggregate KMZ history storage can
reuse these bytes after checking the guards. The same path serves history identity
lookups. Record fields must retain their exact object references; mutable containers
and foreign scalars must retain their exact encoded values. Replacing a field, changing
a measurement in place, or changing nested mutable evidence rebuilds the complete
payload. A frozen dataclass alone does not authorize bypassing these checks.

Description preparation materializes shared source columns once per call. Each fire
selects its latest perimeter and point by position. Complete source schemas are hashed
once, and the selected scalar rows are hashed directly from those columns. The current
row digests accompany the views to description preparation; they are not retained as
an unchecked identity hint for later mutable frame calls. Independent public frame
callers still fingerprint their current latest rows. Unusual column schemas retain the
DataFrame fallback, and unsupported cache values use fresh computation.

The row views borrow source scalars and must remain unchanged during the synchronous
preparation call, matching the existing history-column contract. They do not duplicate
geometry or source-attribute strings. Optional missing fields remain missing, and
original row ordering still decides the latest facts and incident designation.

## Compressed products and failures

The SQLite product row has an explicit `encoding` field: zero means raw logical bytes,
and one means the shared versioned payload frame. Opening a five-column store adds the
field with a zero default, preserving each existing logical value without guessing its
format from a byte prefix. Newly written products use Zstandard framing, with the shared
codec's exact raw fallback for data that does not compress. Checksums always cover the
uncompressed logical payload.

Reads decode the explicit format and verify the logical checksum before returning bytes.
Unknown formats, malformed frames, or checksum mismatches return a miss. A value beyond
the shared codec's 256 MiB decoded limit is computed normally and omitted from storage;
that omission does not disable otherwise healthy caching. Forced invocations still
bypass all persistent reads while writing completed products for later invocations.
The existing transaction, nested-scope health, context-retention, reader, and recovery
contracts are unchanged.

KMZ uses ZIP DEFLATE because the consumer format requires compatible ZIP members. Its
member contents are not changed by the internal product encoding. Qualified aggregate
histories retain their existing per-history Zstandard frames, allowing their current
validation and selection contract to remain intact.

## Costs and verification

Writing a value takes linear time and one output buffer in its encoded byte size,
except frozen-set sorting, which also retains each child encoding and sorts the set.
Recursive depth follows the supported Python recursion limit; arbitrary cyclic graphs
are outside the input domain. Canonical reads still decode and re-encode, so this
change primarily targets forced and cold preparation. Shared qualified payloads retain
one additional immutable copy of each selected history until execution cleanup; this
trades bounded execution-lifetime memory for avoiding another full encoding. The
retention scales with qualified output evidence, not every source history.

Owners are `spatial_data.cache_values`, `frame_fingerprints`, and `product_cache`,
`presentation.prepared_cache`, `fire_data`, `row_values`, and `text`, and
`kml.prepared_inputs`. The checked `CacheCodec.lean` and `CacheDependencies.lean`
contracts were rerun before implementation. An independent binary fixture encoder and
parser connect the actual wire bytes to the existing typed-tree oracle, including all
scalar distinctions, container order, pairwise equality, truncated roots, trailing bytes,
and malformed scalar fields. The formal bridge does not prove Python, Pint, pandas,
NumPy, GEOS, Zstandard, or SQLite themselves.

Ordinary tests additionally cover exact binary payloads, current latest-row keys,
mutable history guards, raw-store compatibility, compressed storage, checksum failure,
unknown encodings, and cache omission. Product transaction and retention conformance
still checks the real SQLite logical products across readers and interruptions. See
[typed cache verification](../../tests/formal/lean/cache_codec.md),
[product caching](product-caching.md), and
[product context retention](product-cache-retention.md).

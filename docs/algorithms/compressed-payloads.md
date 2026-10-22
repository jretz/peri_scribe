# Exact compressed cache payloads

Parsed source caches and prepared products keep their logical bytes intact while storing
smaller BLOBs. Authoritative source files retain their formats, organization, and bytes.
The codec accepts arbitrary bytes, including geometry metadata, dimensional flags,
coordinate bits, and typed JSON. Existing checksums continue to identify the decoded
logical bytes. A digest selects possible equality candidates; complete decoded equality
still decides whether two parsed payloads share an identity.

## Complexity assessment

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | A feed's immutable compression dictionary belongs to its durable cache generation. |
| Rule interaction | 2 | Format markers, raw fallback, dictionary identity, block bounds, and canonical hashes must agree. |
| Mathematical reasoning | 2 | XOR prediction and byte-lane permutation compose without interpreting coordinates. |
| Scale and representation | 3 | Bounded independent blocks and exact reconstruction control working memory and storage. |
| Failure and concurrency | 3 | Dictionary references, payloads, receipts, and occurrence order must survive rollback, readers, and compaction. |

The total is 12, so this behavior is complex. Published products must remain identical;
compression cannot change source interpretation or weaken authentication.

## Framing and reconstruction

Storage metadata explicitly selects raw logical content or version-one framing. Legacy
bytes are never recognized by their apparent magic prefix. Inside a frame, tag `0x10`
means raw content, `0x11` means zstd, and `0x12` means predicted zstd. Bit `0x20` adds an
exact SHA-256 dictionary identity to a compressed frame. Raw frames carry one tag byte.
Compressed frames carry a 13-byte header: tag, unsigned 64-bit original length, and
unsigned 32-bit block count, with integer fields in little-endian order.

Each compressed block carries two unsigned 32-bit lengths followed by one complete zstd
frame. Blocks cover successive original ranges of at most one MiB. Decoding requires
the exact original block size implied by the total length, a supported tag, the expected
block count, bounded compressed lengths, and no trailing bytes or concatenated streams.
The zstd window is limited to one MiB. The optional cache codec permits at most 256
blocks and 256 MiB of decoded content. Larger parsed payloads retain an explicit raw
storage encoding; products can decline optional caching without affecting their output.

Compression uses zstd level three. Values shorter than 256 bytes use raw framing.
Larger values use compression only when the complete frame is smaller than raw framing,
including dictionary identity and block headers. Raw fallback means a small point can
cost one extra byte while avoiding expensive, larger compressed framing.

The predictor applies to arbitrary geometry bytes without parsing WKB. For each block,
append zero bytes to a multiple of 16. Within each byte lane, XOR each original byte
with its original predecessor; the first predecessor is zero. Transpose the resulting
matrix so successive bytes in one lane become adjacent before compression.

For a four-lane illustration, the originals and predictions are:

| Row | Original bytes | Prediction against the previous original row |
| --- | --- | --- |
| 0 | `01 02 03 04` | `01 02 03 04` |
| 1 | `05 06 07 08` | `04 04 04 0c` |
| 2 | `09 00 00 00` | `0c 06 07 08` |

The transposed sequence is `01 04 0c | 02 04 06 | 03 04 07 | 04 0c 08`.
Cumulative XOR reconstructs each original lane; transposing back restores the rows.
The declared original length removes padding. Production uses 16 lanes so consecutive
pairs of binary double coordinates often share predictable bytes. Three-dimensional
geometries, mixed endian encodings, SRIDs, NaNs, and non-coordinate bytes remain exact;
they can merely compress less effectively.

For originals `x[i]` and a zero predecessor, prediction is
`y[i] = x[i] XOR x[i-1]`. Reconstruction gives
`y[i] XOR x[i-1] = x[i]`, because XOR is associative and `a XOR a = 0`.
Induction recovers every byte. Matrix transposition is its own inverse, and trimming
appended padding retains the original prefix. No floating-point operation occurs.

## Per-feed dictionaries and publication

Each parsed-cache generation may train one immutable 16 KiB attribute dictionary.
Training selects at most 256 deterministic sparse samples in payload-ID order. Each
sample contributes at most 64 KiB, and all samples together contribute at most four MiB.
Fewer than eight samples or 32 KiB of material leave values independently compressed.
Training failure has the same result. Dictionary training is an optimization; its output
need not stay identical across future zstd releases because dictionary bytes persist
alongside every referring payload and the frame authenticates their exact identity.

The writer inserts the dictionary and rewrites referring attribute encodings inside the
same SQLite transaction that publishes source receipts and row references. Readers pin
one transaction and obtain dictionary bytes through that connection. The dictionary is
never retrained while its generation survives. Changed source schemas still produce
valid compressed or raw values. Geometry and attribute payload tables record the exact
original byte length for admission scheduling; decoding checks that metadata again.

SQLite's BLOB affinity permits other stored types. Readers reject dictionary values
that are not bytes with a `ValueError`, so damaged entries follow the source fallback
path before frame authentication or decompression.

| Boundary | Observable result |
| --- | --- |
| Dictionary inserted, referring values incomplete | Other readers retain the committed generation. |
| Transaction rolls back or writer terminates | SQLite restores the prior complete dictionary and values. |
| Transaction commits | Dictionary, references, and values become visible together. |
| Dictionary missing, changed, or framing invalid | Parsed cache falls back to authoritative source parsing; product cache misses. |
| Compaction | All six tables, including dictionaries, preserve exact rowids and values. |

The standalone [cache upgrade](../../migrations/compress_parsed_cache.py) accepts explicit
schema-eight cache paths. It authenticates every original logical checksum, updates
encodings transactionally, and preserves payload IDs, receipts, memberships, and rowids.
It is idempotent. After its writer closes, ordered compaction explicitly repacks
within-page slack; the usual freelist threshold cannot detect all space left by smaller
BLOBs. Runtime schema incompatibility remains a safe disposable-cache rebuild.

## Costs, alternatives, and limits

For a payload of `n` bytes, prediction, checksumming, and reconstruction take `O(n)` time.
Codec scratch is bounded by one block, plus the complete input/output required by the
bytes API. Peak decoding can include the growing bytearray and its final immutable copy.
This codec bounds individual payloads; pipeline admission controls concurrent payloads.
Dictionary storage is 16 KiB per trained feed, and training input is bounded independently
of feed size. Digest candidate collisions require exact decompression and comparison;
hashes do not replace equality.

Plain zstd was measured to save about 17.6% of geometry bytes, while prediction and lane
shuffling saved about 41%. Normalizing coordinate numbers or changing authoritative
source formats would add unnecessary semantic risk. Whole-cache archive compression
would obstruct indexed reads and bounded hydration. Independent framed BLOBs preserve
SQLite lookup granularity and permit per-block decompression bounds.

On the profiled corpus, upgraded and ordered-compacted cache files decreased from
534,827,008 to 257,998,848 bytes. Every logical payload, metadata row, sparse occurrence
key, and receipt matched the originals. These are measured database file sizes, including
indexes and page layout; savings on other source collections depend on their data.

The design assumes SQLite transaction isolation, cooperating writer ownership, and the
existing atomic replacement contract. Power-loss guarantees, arbitrary filesystem
corruption, zstd's implementation correctness, and NumPy's implementation correctness
remain outside the formal proof. Logical checksums and source fallback provide the
existing runtime validation boundaries.

## Implementation and verification

- [Shared codec](../../src/spatial_data/payload_codec.py) and
  [byte prediction](../../src/spatial_data/payload_prediction.py) own exact framing.
- [Parsed payload storage](../../src/peri_scribe/geo/payload_storage.py),
  [database](../../src/peri_scribe/geo/database.py), and
  [decoding](../../src/peri_scribe/geo/dictionaries.py) own storage metadata and dictionaries.
- [Lean contract and limits](../../tests/formal/lean/payload_codec.md) explain proved XOR,
  transpose, and padding identities and executable implementation conformance.
- [Normalized cache publication](../../tests/formal/tla/NormalizedCache.tla) and
  [ordered compaction](../../tests/formal/tla/cache_compaction.md) retain their transaction
  and exact-copy guarantees; the compaction configuration covers six tables.
- [Codec tests](../../tests/tests/standard/spatial_data/test_payload_codec.py) cover block
  boundaries, framing corruption, raw fallback, dictionaries, and bounded decoding.
  [Storage tests](../../tests/tests/standard/peri_scribe/geo/test_payload_storage.py) check
  transaction visibility, rollback, dictionary failure, and canonical checksums.

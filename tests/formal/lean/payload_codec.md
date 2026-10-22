# Exact payload prediction

[PayloadCodec.lean](PeriScribe/PayloadCodec.lean) proves that recursive XOR restoration
inverts prediction for every finite list of eight-bit values and every predecessor.
Prediction is therefore injective. It also proves that transposing a finite rectangular
byte matrix twice is identity and that trimming appended padding retains the complete
original prefix. These proofs use exact bit vectors, without floating-point arithmetic.

The design was checked before implementing the Python predictor. The algorithm and its
five-dimension assessment are documented in
[exact compressed payloads](../../../docs/algorithms/compressed-payloads.md).

## Concrete adapter

`encodedLanes` provides an executable list representation: zero-pad to a complete lane
width, select bytes by their index remainder, predict each lane from zero, and flatten
lanes in column order. `OraclePayloadCodec.lean` exposes that representation through
`oraclePayloadCodec`. The [conformance test](../conformance/test_payload_codec.py) compares
actual NumPy prediction with this executable for 201 cases, including empty values,
every length through 65, all byte values across offsets, and longer digest-derived
values. It also reconstructs each result and round-trips complete production frames.

The unbounded proof covers lane recurrence, mathematical transposition, and prefix
retention. The concrete list-index adapter and its equivalence to NumPy layout are
checked over those finite examples; they are not an unbounded proof of NumPy. Ordinary
and generated tests additionally cover arbitrary bytes, block boundaries, dictionaries,
raw fallback, malformed lengths, missing dictionaries, and trailing zstd frames.

## Durable storage assumptions

The existing `NormalizedCache` model was rechecked before implementation. A durable
logical payload maps to the complete stored encoding together with its immutable
compression dictionary. Decoding projects that pair to the exact logical bytes proved
above, assuming zstd correctness. Dictionary insertion, referring values, row references,
and receipts share one SQLite transaction, so no new independent publication action is
introduced. Concrete tests verify committed versus rolled-back dictionaries through a
second SQLite connection and reject changed dictionaries before returning payloads.

`ParsedCacheCompaction` includes six tables and preserves every stored value and implicit
rowid, including the new dictionary table. Concrete path conformance covers each copy,
validation, closure, interruption, and publication boundary. An explicit repack request
changes admission only; it retains the same publication protocol and excludes WAL.

Neither model proves zstd, SQLite, NumPy, cryptographic collision resistance, or power-loss
semantics. Canonical hashes still select candidates, and exact decoded equality resolves
candidate collisions. Caller authentication and malformed-frame rejection remain
ordinary adapter obligations. Source files are never transformed by this codec.

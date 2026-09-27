# Typed cache representation

`CacheCodec.lean` proves an ordered tagged-tree codec over arbitrary finite trees.
Scalar leaves carry a type tag and an exact sequence of natural-number byte values.
Empty containers and nonempty ordered containers have distinct constructors. Prefix
encoding retains both children of every branch and tags every constructor, so neither
container boundaries nor scalar fields can be confused.

The 14 theorems establish decoding with an arbitrary suffix, round trips, injectivity,
equivalence of encoding equality and value equality, distinct scalar types and payloads,
preserved child order, a sufficient parsing-fuel bound, canonical accepted roots, and
rejection of appended trailing tokens. The executable `oracleCodec` uses these exact
encoding and decoding definitions. The oracle's token transport is not the production
JSON format; the bridge lowers both declared and actual JSON trees into this grammar.

## Implementation connection

`helpers/cache_codec.py` specifies 50 scalar fixtures independently of
`spatial_data.cache_values.encode`. These include all three missing sentinels, booleans,
arbitrary-size integers, signed zero, neighboring floating-point bit patterns, infinities,
distinct NaN payloads, text, bytes, enum identity, original measurement units, datetime
offset/fold, pandas timestamp resolution, nanosecond durations, NumPy type/bytes, and
geometry WKB/SRID. They compose into 178 values including nested containers, ordered
mapping permutations, empty containers, and canonically ordered frozen sets.

The bridge compares each real stored payload and its decoded/re-encoded result with the
declared tree through Lean, also checking the restored Python type. It checks all 15,753
pairs against the proved equality relation, including pairs intentionally equal under
frozen-set permutation. A further 356 malformed prefix cases exercise incomplete roots
and appended values. Ten actual decoder fixtures reject noncanonical duplicate mapping
keys/set elements, invalid scalar shapes, unsafe NumPy storage, and unapproved enums.
Those last decoder rejections are finite implementation checks, not a proof of Python's
complete input-validation grammar.

## Boundaries

The mathematical result concerns tagged tree structure and exact scalar payloads. The
Python bridge uses UTF-8 bytes and preserves every JSON field; the theorem does not
prove Python's JSON parser, Unicode encoding, NumPy, pandas, Pint, or GEOS. Geometry is
represented by WKB, rather than geometric equivalence. Datetime semantics retain the
serialized instant/offset/fold, not a named timezone's future transition rules.
Supported enums require the caller's explicit allowlist. Frozen sets are compared by
their canonical ordered representation; arbitrary Python object graphs and cyclic
containers are outside the codec's domain. Hash collision resistance remains a separate
assumption of the cache-key models.

The source owner is `src/spatial_data/cache_values.py`; conformance is
`conformance/test_cache_codec.py`. Changing tags, supported types, canonical ordering,
or retained fields requires updating the declared representation fixtures and the
appropriate proof boundary together.

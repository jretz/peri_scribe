# Typed product caches and published-row reuse

## Contract and assessment

The caller must be able to recompute a result whenever these disposable caches miss. A
hit has a stronger obligation: it must reproduce a completed deterministic product for
the current dependency context, namespace, and ordered inputs. The row index
additionally binds normalized groups to the authenticated checksum of the authoritative
published artifact. Callers supply complete dependencies and complete post-GDAL groups;
the cache cannot infer an omitted policy input or verify source truth.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | Manifest replacement and pruning select one complete artifact generation while retaining shared payloads. |
| Rule interaction | 3 | Context, key, storage checksum, content digest, artifact checksum, schema, and row identity jointly permit a hit. |
| Mathematical reasoning | 1 | Ordered tagged encoding and hash composition use standard dependency-preservation arguments. |
| Scale and representation | 2 | Per-row fingerprints and content-addressed groups avoid materializing unrelated histories. |
| Failure and concurrency | 3 | Payload, manifest, prune, and commit operations interact with interruption, nesting, and SQLite failures. |

**Complex: 11.** A false hit can publish stale geometry or attributes. Safe fallback is
therefore more important than maximizing reuse.

## Evidence identity before storage

The typed codec distinguishes `None`, `pd.NA`, `pd.NaT`, boolean/integer types, exact
floating-point bytes, container order, original quantity units, timestamp precision,
NumPy dtype/bytes, and geometry WKB/SRID. Enums require an explicit decoding allowlist.
Canonical re-encoding must equal the stored bytes. Arbitrary object graphs, unsafe NumPy
object/structured scalars, and executable serialization are outside its domain.

`frame_rows` hashes schema (ordered columns and dtypes, active geometry name, and CRS)
and each row independently. The selected key hashes caller identity plus each selected
schema and **ordered** row-digest sequence. Index labels are excluded because consumers
select positionally. A SHA-256 collision-resistance assumption is separate from the
codec's preservation of exact values.

![Ordered evidence becomes a complete structured cache key](assets/cache-evidence.svg)

Rows `[A,B]` and `[B,A]` contain the same members, but their order can change the
result. The cache key preserves that distinction. Changing a column type, CRS, original
unit, or canonical fire identity also changes the relevant key input.

For example, replacing `1 acre` with its equivalent quantity in square meters changes
the representation and invalidates the row key even if a particular displayed value is
unchanged. Relabeling a DataFrame index does not. This conservative invalidation is
intentional. Hashing only geometry would wrongly reuse descriptions after an attribute
correction; hashing only a file path would miss replacement content at that same path.

## Prepared history identities

After canonical decoding, domain validation and exact reserialization, a history can
retain its canonical immutable payload and SHA-256 digest within the owning execution
scope. Descriptions use that digest as a dependency; qualified aggregate storage reuses
the payload. Both paths validate the mutation guards before reusing either value.
The registry retains the exact history object, preventing object-ID reuse from matching
unrelated evidence. Scope exit releases the registry.

Per-fire selection retains guards eagerly only when historical area meets the map's
inclusion threshold. Smaller or unknown histories remain complete and fully validated;
their first description request serializes the current evidence and captures guards
then. Generic history reads still retain identities by default. Declining admission
changes memory use without changing qualification, accepted values or cache keys.

Frozen records can contain mutable children, including measurement dictionaries and
Pint quantities. Guards check each record field by reference, traverse exact tuples and
retain one detached typed encoding of the ordered mutable and foreign scalar children.
Each digest lookup checks that tuple in one codec pass. A changed field, ordered
dictionary, numeric type, floating-point encoding, original unit or extended dataclass
invalidates the digest. The complete serializer then constructs a fresh current identity.
Native immutable scalars need no independent encoding guard. Callers keep the evidence
stable while each synchronous check or encoding runs.

This adapter is involved: history 1, rules 2, mathematics 1, representation 2, effects 1;
total 7. Its invariant is equality with hashing the complete current canonical history
payload. The existing ordered-codec and complete-dependency theorems provide the
composition argument; guarded-description conformance additionally mutates nested
measurements and quantities inside one live execution. The enclosing complex cache
assessment remains applicable.

Execution-level index and score keys retain compact digests of freshly serialized
documents. Serializing current contents on each lookup still detects a model's mutable
alias collection changing in place. Plot keys rebuild dataclass containers while
borrowing scalar values for synchronous typed encoding, preserving all renderer,
locale and time-zone dependencies without recursive scalar copies.

The [KMZ preparation](kmz-preparation.md) aggregate binds complete qualifying histories
to authenticated geography bytes, index and policies. A miss retains the ordinary
per-row/per-fire cache path; the aggregate does not replace those fine-grained keys.

## Transaction and read invariants

A scope owns a SQLite connection and an 8 MiB configured page cache. Successful scope
exit commits; an exception closes the uncommitted transaction. Nested scopes at the same
resolved path borrow the connection, temporarily select their context, and cannot clear
an ancestor's forced-miss flag. A separate-path scope owns its own connection. Unavailable
storage or statement errors disable cache reuse so the caller can compute fresh results.
An earlier successful statement can still commit after a later statement error; the
protocol does not assume that every statement failure rolls back the whole transaction.

After a healthy application commit, [context retention](product-cache-retention.md)
retires obsolete dependency contexts in a separate transaction and reclaims their
physical pages when possible. Every context admitted by the outer scope or its
same-path nested scopes remains available. Cleanup failure can defer reclamation without
undoing the completed products.

The publication transaction makes the complete generation visible together:

1. Write typed group payloads under their content digests, for example group `A` under
   digest `a` and group `B` under digest `b`.
2. Replace the complete ordered manifest, recording the artifact checksum, column
   order, and group-to-digest entries such as `(A, a)` and `(B, b)`.
3. Prune unreferenced payloads in that namespace and context, keeping `a` and `b` while
   removing obsolete payloads.
4. Commit the SQLite transaction on successful scope exit.

A reader authenticates the requested generation before treating any selected history
as reusable. Reads require a valid manifest with the caller's artifact checksum. Each
selected manifest group's payload must exist, match its content digest, decode
canonically, preserve exact column order, and contain the promised derivation key in
every row. A damaged selected group yields `None`, and the caller falls back to the
artifact. Requested keys absent from the manifest are omitted from the result. An
authenticated selection with no matching groups returns `{}`; a miss must not be
confused with that empty result. Corruption in an unrequested group does not prevent
reuse of valid requested groups.

An adaptive read of a nonempty manifest chooses bulk decoding when the caller requests
the entire layer with `requested_keys=None`, or when at least 128 requested keys are
present in the manifest and cover at least half its groups. That is a performance
decision; it changes neither artifact ownership nor the valid-result contract.

## Costs, alternatives, and verification

Let B be serialized input bytes, R row count, S selected row count, G manifest groups,
and P requested payload bytes. Initial fingerprints cost O(B) and retain O(R) fixed-size
digests. Selected-key construction costs O(S) digest material plus caller identity/schema.
Reading a row index scans O(G) manifest entries and decodes O(P) bytes. The full manifest
is retained even for a small selection. Codec work is generally proportional to data
size, with additional sorting for frozen sets. Returned mutable containers are freshly
decoded. SQLite's page-cache setting does not bound all process memory or result size.

An in-memory object cache would be simpler but retain large inputs and outputs. A
whole-frame disk cache would lose selective reuse. This design pays the cost of hashing
each row and reading a manifest so callers can avoid decoding unrelated histories. No
cache is an authoritative backup. Digest authentication detects inconsistency under
trusted storage assumptions; it is not a signature defending against an attacker who can
replace data and every checksum.

Implementation: [cache_values.py](../../src/spatial_data/cache_values.py),
[frame_fingerprints.py](../../src/spatial_data/frame_fingerprints.py),
[product_cache.py](../../src/spatial_data/product_cache.py), and
[row_index.py](../../src/spatial_data/row_index.py).
Ordinary tests cover [codec](../../tests/tests/standard/spatial_data/test_cache_values.py),
[fingerprints](../../tests/tests/standard/spatial_data/test_frame_fingerprints.py),
[store lifecycle](../../tests/tests/standard/spatial_data/test_product_cache.py), and
[row selections](../../tests/tests/standard/spatial_data/test_row_index.py).

[CacheCodec](../../tests/formal/lean/cache_codec.md) proves tagged-tree preservation;
[CacheDependencies](../../tests/formal/lean/cache_dependencies.md) proves the declared
dependency obligation. Their [codec](../../tests/formal/conformance/test_cache_codec.py)
and [dependency](../../tests/formal/conformance/test_cache_dependencies.py) bridges
exercise actual representations and selected production consumers.
[CacheRead and ProductCache](../../tests/formal/tla/cache.md) model bounded selection and
transaction cases, connected by [conformance](../../tests/formal/conformance/test_product_cache.py).
The models assume complete initial generations, correct caller dependencies and artifact
checksums, SQLite atomicity, and cooperating ownership. They do not prove every caller's
dependency inventory, SQLite internals, hash collision resistance, or power-loss durability.

[Prepared product representations](prepared-product-representations.md) describes the
binary codec, framed key preimages, current latest-row views, and compressed SQLite
values. These internal representations preserve the logical cache contracts above.

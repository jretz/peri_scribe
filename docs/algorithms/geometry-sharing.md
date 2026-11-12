# Immutable geometry sharing

## Contract and assessment

A source read owns one `GeometryPool` so repeated geometry can share one immutable
Shapely object. Sharing requires identical canonical WKB, including dimensions and SRID.
Distinct WKB must remain distinct even if SHA-256 digests collide. Updates replace an
immutable root and share unchanged branches, so an earlier snapshot still describes its
original entries.

| Dimension | Score | Reason |
| --- | --- | --- |
| History and state | 2 | New roots preserve the meaning of retained historical snapshots. |
| Rule interaction | 2 | Highest differing digest bits determine insertion above or below an existing branch; collisions require exact comparison. |
| Mathematical reasoning | 2 | Compressed trie routing and decreasing split bits establish bounded depth and lookup preservation. |
| Scale and representation | 2 | Digest prefixes share tree paths without retaining another complete copy of each WKB. |
| Failure and concurrency | 2 | Each digest shard serializes root replacement and decoded-object reuse; snapshots acquire shard locks in a fixed order. |

**Complex: 10.** Sharing is an optimization; preservation of exact geometry and spatial
reference is the required correctness property.

## Compressed trie and insertion argument

Within each digest shard, each leaf stores one digest and a tuple of candidate
geometries. A branch stores a representative digest, the highest bit at which its
children differ, and two child roots. Common digest prefixes do not need separate nodes.
Along a path from root to leaf, each branch splits on a lower-ranked bit than the
preceding branch. A new digest that differs above the current split creates a new
parent; otherwise its bit at the current split selects the recursive child.

![Insertion publishes a new root while preserving the saved subtree](assets/geometry-trie.svg)

*Within one shard, the new parent and leaf move into place and connect before the
current pool root changes. The saved snapshot keeps its original pointer, and its
subtree stays fixed: insertion shares those objects instead of copying or mutating them.
The three static graphs show the initial tree, the constructed but unpublished root, and
the published result when motion is unavailable. The replay resets the example; it does
not remove a live entry.*

The four-bit digests are illustrative; production SHA-256 digests have 256 bits. Both
old leaves remain reachable after the new root is created. This insertion differs above
the old root, so it needs no copies along an existing branch path.

The invariant is that every child shares its parent's higher prefix, routes on the
appropriate split bit, and has only lower split ranks. Inserting above a branch
preserves all its existing routes; inserting below replaces only the chosen path. A
representative digest always comes from its subtree. Thus every old entry remains
discoverable and the new entry follows the same lookup rule. This avoids an ordinary
unbalanced binary tree's linear depth on sorted digests; a trie path has at most 256
branch ranks plus its leaf.

## Collision example and ownership

Equal digest values are insufficient evidence of equality. The bucket comparison must
include coordinate dimensions and SRID, as well as the coordinates.

For a deliberately colliding digest, requests under their shared digest-shard lock
behave as follows:

1. Insert A, a 2D point with SRID 4326: create one bucket entry for A.
2. Insert B, a 3D point with SRID 4326 and the same digest: compare full
   `to_wkb(..., include_srid=True)`, add a second bucket member, and preserve A.
3. Request A's exact WKB again: return A's existing object and leave the root unchanged.

Comparing digest alone would silently substitute the wrong geometry. Geometrically equal
polygons with different canonical vertex order also remain distinct. Sharing requires
the same encoded representation, even when two encodings describe the same shape.

`from_wkb` computes the digest and chooses its integer value modulo sixteen before
acquiring that shard's lock, then performs lookup, decode, and root replacement while
holding it. Two simultaneous requests for the same canonical bytes therefore share one
object. A global interning cache could retain an entire process history; a pool per
source read bounds its lifetime to that owner. Holding historical roots deliberately
retains their reachable objects. Malformed WKB raises through the decoder; no partially
constructed root is installed.

## Costs and verification

For byte length B and a collision bucket of C entries, hashing is O(B); trie traversal
visits at most 256 branch ranks. Collision checks can serialize and compare C
geometries, so their byte cost matters even though digest depth is fixed. An insertion
copies only its path and any changed bucket; U distinct digests require O(U) nodes, plus
geometry payloads. Historical roots can retain path copies. Each lock serializes
decoding in its digest partition; unrelated partitions can proceed independently. This
does not promise parallel insertion throughput or eventual reclamation.

Implementation: [geometry_pool.py](../../src/spatial_data/geometry_pool.py). [Ordinary
tests](../../tests/tests/standard/spatial_data/test_geometry_pool.py) and [generated
tests](../../tests/tests/property_based/spatial_data/test_geometry_pool.py) exercise
collision safety, representation, and persistence.
[GeometrySharing](../../tests/formal/lean/geometry_updates.md) proves reachable trie
validity, insertion/lookup agreement, collision preservation, persistent snapshots, and
the digest-width depth bound.
[Conformance](../../tests/formal/conformance/test_geometry_sharing.py) compares actual
trees with the executable model and includes real concurrent requests with forced
collisions. The test adapter carries each branch's required digest prefix to its
children. A branch splitting at the second-lowest bit requires its smaller child to
share its higher bits followed by 0 at that bit, and its larger child to share them
followed by 1. A deeper split constrains more bits while preserving that route. The
adapter also checks that every branch representative occurs among the leaves. Any
matching leaf must be in that branch's subtree because a leaf in a different branch
would disagree at the first divergent split. Every selected historical root receives
the same complete traversal. The adapter retains the EWKB bytes alongside a strong
reference to each observed immutable Shapely object. Visits to that same object share
its exact bytes. Every insertion still checks the bytes returned by the production call.

The test adapter scores **1/1/1/2/1 = 6, involved**. It retains ordered prefix roots,
combines routing and representative checks, and validates a compact response before
expanding it. For N nodes and P payloads, each description takes O(N + P) time and
space with the fixed digest width and payload catalogue. Geometry bytes add their own
serialization cost. The Lean validity and insertion definitions supply the expected
contract.

The oracle folds the same proved insertion over every prefix. Each response carries
the roots in insertion order and a table of their exact immutable nodes. Each branch
record names the two ordered child records, and each leaf records its ordered payloads.
Digest ordinals identify exact inputs in their order of first occurrence. For example,
two roots that share a leaf can both name record 0. A branch with the same digest and
split bit but reversed children has a different record. The reconstruction theorem
shows that exact node records and their child descriptions determine the full ordered
tree. [GeometrySharing.lean](../../tests/formal/lean/PeriScribe/GeometrySharing.lean)

Python checks the digest, payload and node references, rejects duplicate or unreachable
records, and expands every root occurrence to its complete length-framed description.
For a history of H entries, the oracle performs H insertions, visits all N node
occurrences and writes D distinct node records and H roots. Packing takes expected
O(N) time with bounded digest width and payload count per leaf. The wire and decoder's
node table use O(D + H) space, and full expanded comparisons can take O(N) space. The
prefix length bounds each expansion. The two 256-entry width histories retain all
131,072 node occurrences in 33,407 records. A separate regression checks the decoded
results against the direct Lean descriptions for the small collision histories and
permutations. [Conformance](../../tests/formal/conformance/test_geometry_sharing.py)

The source-read registry also assigns compact exact `.wkb` class keys
without retaining all encoded coordinate buffers; its SRID-ignoring equality is separate
from this pool's EWKB equality. See [source geometry
preparation](source-geometry-preparation.md). Canonical WKB serialization, Shapely
immutability, and Python locks are trusted boundaries. Noncanonical byte-order variants
are outside the exact-byte reuse guarantee.

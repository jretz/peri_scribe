# Source-index preparation and authenticated dependency reuse

## Contract and context

Source indexing must produce the same ordered fire index as complete interpretation of
the authoritative snapshots. The work includes byte authentication, parsed evidence,
identity connectivity, complete fire fingerprints, border classification and publication.
Every row occurrence, source path, attribute and complex declaration remains evidence.
The pipeline covers the United States; the California classifier is one derived policy.

The preparation optimizations share exact representations and reuse unaffected
dependency blocks. They do not replace an independent invocation's source-byte checks
with timestamps. A scope owns stable source inputs, and its authentication evidence ends
when that scope ends. Inode, change-time, modification-time and size comparisons detect
changes that produce a different filesystem stamp. Changes observed during a checksum
operation cause rejection.
Cooperating pipeline writers retain the existing year lock; arbitrary external changes
that defeat both ownership and reliable metadata remain outside this contract.

Nanosecond timestamp fields describe units, not guaranteed clock precision. A rapid
same-size overwrite with restored modification time can retain the entire stamp if
change time has not advanced. [Linux inode timestamps](https://docs.kernel.org/filesystems/multigrain-ts.html)
can share one clock tick. Such indistinguishable edits violate the stable-input premise
within a scope; independent invocations always read fresh bytes, even with equal stamps.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 2 | Saved grouping blocks and source manifests can serve later generations only when their complete dependencies still match. |
| Rule interaction | 3 | Identity connectivity, ordered raw evidence, classification dependencies and authenticated generations must agree. |
| Mathematical reasoning | 2 | Geometry equality, conservative dependency closure and Merkle framing have distinct correctness boundaries. |
| Scale and representation | 3 | Dictionary references and row fingerprints avoid repeatedly transferring and normalizing large coordinate and attribute payloads. |
| Failure and concurrency | 3 | Scope expiry, SQLite publication and independently durable source changes must not expose stale evidence. |

**Total 13: complex.** The existing parsed-cache, grouping, geometry-sharing and product
cache notes remain authoritative for their respective policies. This note connects the
preparation stages and explains authentication and manifest composition.

## Approach and invariants

Complete and selective reads carry one explicit `SourcePaths` owner for their exact
lexical source directory. Dependency rows, per-fire evidence fingerprints and index
output share its relative strings. Every stock immutable source path is converted by
the original `Path.relative_to` at most once per owner; subsequent consumers reuse that
same string. No resolution, normalization or filesystem check is added. Sorting remains
an output operation, and repeated source occurrences retain their multiplicity.

The memo belongs to the read and its groups. Releasing those objects releases its
strings; retaining a read explicitly retains them. Callers treat the memo dictionary as
read-only, and only its lookup method adds freshly derived values. There is no global
or copied-context cache. Keys retain exact path type and string, and owners require the
exact lexical root string. Windows Path equality ignores case, so using Path objects as
keys would incorrectly alias differently spelled filenames. Custom source or directory
subclasses call their current `relative_to` method each time. Original errors propagate
and are not retained. These strings carry no filesystem evidence and authorize no
checksum, parse or publication shortcut.

This local memo refinement has scores **1 history, 1 rules, 1 mathematics, 1 scale and
0 failure/concurrency: total 4, straightforward**. Its state contains only pure derived
strings; complete directory/path keys preserve their meaning. For R row and output
occurrences over S distinct source paths, repeated lexical ancestor traversal falls from
O(RL) to O(SL + R) expected work, where L is path depth. The memo retains O(S) paths and
strings within the existing preparation lifetime. Hash-table lookups retain their usual
worst-case linear bound. The complete preparation retains its complex assessment above.

Authenticate each authoritative snapshot once in an owning preparation scope. Retain its
SHA-256 and full filesystem stamp in that scope. A repeated request can reuse that
evidence only while the scope is live, in the same process, within its source directory,
and with the same stamp. A new scope hashes bytes again, even when every stamp matches.
The reader still selects a matching cache receipt, rows and memberships within one
SQLite transaction. Sharing a checksum does not authorize reading a different parse.

The first inventory read records pending evidence under its absolute input path after
checking the complete stamp before and after hashing. It defers canonical path
resolution because an unchanged published index may need no later source preparation.
Pending evidence is never borrowed directly. A subsequent request resolves the current
path inside the owning source directory, checks the live process and complete current
stamp, and only then admits that evidence to the ordinary checksum cache. Repeated
inventory requests use that same admission path. Outside paths always read fresh bytes,
and retargeting a file or ancestor symlink cannot bypass canonical admission. Process
identity is checked before acquiring a scope lock, including cleanup, so an inherited
locked scope cannot block a different process.

Inventory authentication distributes previously unseen absolute paths into at most four
strided batches, capped by the available CPU count. A worker reads complete bytes and
compares the full filesystem stamp before and after each read. It receives only its paths
and a cancellation event; it never inherits the owning context or accesses its evidence
dictionaries or lock. The
caller joins every worker before checking the live process and current stamps again.
Only a complete matching batch can add pending evidence, under the owning lock. A read
failure, cancellation, expired owner or changed stamp returns no partial batch. Pending
publication does not change canonical admission: later consumers still resolve the
current path and enforce the source-directory boundary.

The ordered batch API preserves every requested occurrence. Duplicate or previously
authenticated paths use ordinary inventory admission, while the first occurrence of a
new path receives its freshly read digest. Empty and singleton inventories and calls
without a live owning scope retain the serial reader. Generation creation requests this
batch only after its existing execution-local metadata cache misses; the manifest receives
the same ordered relative paths and SHA-256 strings. Neither source-generation framing
nor persistent cache formats depend on worker completion order.

A domain-separated Merkle manifest combines the ordered relative snapshot paths and
their freshly authenticated digests. Each leaf starts with byte zero, followed by the
path and content fields in UTF-8. The shared `sources.digests.framed_value` encoding
escapes every literal zero as `00 01` and terminates each field with `00 00`. A branch
starts with byte one and contains two ordered, fixed-width SHA-256 child digests; an
empty inventory hashes byte two. These boundaries preserve empty fields, embedded
zeros and Unicode paths. At each level, adjacent children form a branch and an unpaired
final child advances unchanged. Completed branch identities can be reused when both
ordered child identities match. A context change still invalidates the complete source
generation independently of the source manifest.

Before reading branch receipts, a complete-input key frames the ordered path and checksum
fields and hashes their concatenation. Every occurrence contributes exactly two fields,
so this encoding retains pair boundaries, ordering and multiplicity. A checksum-protected
completed-root receipt for that exact key bypasses branch decoding, leaf hashing and
branch serialization. Its payload must be a canonical lowercase hexadecimal SHA-256
identity. A missing or malformed receipt runs ordinary Merkle composition and stores the
completed result. Only the current completed-root receipt is retained, with replacement
and pruning in the same owning product transaction.

Merkle composition does not remove the compulsory byte scan. For B authoritative bytes,
S snapshots and D changed leaves, authentication remains O(B). Hierarchical composition
can reuse unchanged branches; the inventory comparison remains O(S), and hashing changed
ancestor paths costs O(D log S) with stable topology. Insertions or removals can change
that topology and require more branch work, up to O(S). Every invocation still hashes
the complete ordered input-key fields, using O(S) references and work proportional to
their total byte length. A completed-root hit avoids all branch work. A miss also hashes
all leaves, visits every branch and serializes the current branch receipts, using O(S)
space and work plus the leaf-field byte length. The changed-ancestor bound describes
internal hash calculations on a miss, rather than the complete manifest operation.

With P workers, where P is at most four and at most the number of fresh paths, byte
authentication still performs O(B) work and retains O(S) fixed-size evidence. Each worker
streams one file at a time, so at most P files and P hashing buffers are open. Ideal wall
time approaches the largest strided batch's byte-read time; skewed file sizes, storage
bandwidth and concurrent disk users can limit the gain. Submission creates P tasks, not
one future per snapshot. Cancellation stops remaining reads between files and joins
in-flight reads before returning the original exception. It cannot interrupt an operating
system read that has not returned. The worker cap bounds I/O pressure independently of
the pipeline's geometry worker count.

## Worked examples and boundaries

Suppose snapshot A changes while snapshot B stays identical. The new scope hashes both
files. A's leaf changes and B's leaf remains the same; only ancestors with changed child
identities need new aggregate hashes. The parsed reader consumes these same authenticated
digests, avoiding another two complete hashing passes. It accepts B's existing parse only
with B's matching receipt inside the pinned transaction.

Restoring a file's modification time after changing its bytes cannot carry evidence into
a new scope: every independent scope reads the bytes. Within a scope, the change-time
and inode fields also invalidate an old receipt. Expired copied contexts cannot revive
the old scope. Output files and code outside the source directory do not borrow this
source-authentication shortcut.

## Implementation and verification

[`SourceProvenance.lean`](../../tests/formal/lean/PeriScribe/SourceProvenance.lean)
checks pure memo result preservation, insertion invariance and equality with a complete
ordered map before implementation. Its [inventory](../../tests/formal/lean/source_provenance.md)
states the stable-key and read-only memo assumptions. Executable conformance compares
518 histories across exact lexical paths and roots. Ordinary tests cover stock Windows
and POSIX paths, case-sensitive lexical memo keys, custom source and directory subclasses,
unchanged errors, separate owners, sorted duplicate output paths and one derivation shared
across all three consumers. These checks do not prove pathlib internals or filesystem
identity.

The finite `SourceAuthentication` model checks checksum correctness, lifetime expiry,
cross-scope rejection and invalidation across two edits and two scopes. Check the model
before implementing its scope adapter. Its stable checksum-operation and reliable
metadata assumptions are explicit; it does not prove filesystem, SHA-256 or SQLite
implementation correctness. Ordinary regressions must cover timestamp-preserving edits,
replacement, changes while hashing, nested scopes, expired copied contexts and failures.
Conformance alternates initial inventory reads and canonical authentication in both
starting orders over every checked history. Concrete regressions also exercise outside
symlinks, retargeted ancestor symlinks, pending-evidence expiry and concurrent mixed
requests. Deferred admission changes representation work, not the required source-byte
scan or the checked evidence eligibility policy.

Timestamp-preserving mutation fixtures establish the model's changed-stamp premise by
waiting for an observed change-time difference after the real write. They preserve
modification time and fail with stamp diagnostics if the bounded wait expires. A fixed
sleep cannot establish that premise across filesystem clocks. Separate regressions keep
the entire stamp constant across independent scopes and require a new complete byte read.

The finite `ParallelSourceAuthentication` model adds two independent source batches, one
edit per source, worker failure, cancellation, scope expiry and process replacement. It
checks that workers never publish, every publication follows the complete join, failures
cannot publish, and returned evidence matches current stamps in a live owning process.
The model is checked before implementing parallel authentication. SHA-256, reliable full
stamps and a stable atomic per-file read remain environmental assumptions; a detected
mid-read mutation maps to worker failure. Canonical paths, duplicate occurrences, actual
thread shutdown and bounded open-file counts remain concrete adapter obligations.

The [parallel conformance check](../../tests/formal/conformance/test_parallel_source_authentication.py)
replays every checked edge with its complete admitted prefix through actual isolated
reads and pending publication. The [ordinary authentication checks](../../tests/tests/standard/peri_scribe/sources/test_authentication_parallel.py)
hold real workers across failure and interruption, reject edits and expiry before
admission, and check mixed consumers and retargeted parent symlinks. The
[generated inventory check](../../tests/tests/property_based/peri_scribe/sources/test_authentication.py)
compares ordered duplicates and successive source edits with independent SHA-256 values.

Persistent manifests use the existing transactional product-cache publication contract.
Malformed or unavailable manifests are misses. Their decoded schema and child identities
must validate before subtree reuse. The source generation includes the current derivation
context and the new root, and published outputs retain their own independent checksums.

[`SourceManifest.lean`](../../tests/formal/lean/PeriScribe/SourceManifest.lean) proves that
the root retains the complete ordered tree under an explicit injective node-hash premise.
It also proves that equal ordered children preserve a completed branch's identity.
Its complete-input proof establishes that flattening fixed path/checksum pairs and
applying the shared field encoding is injective, before cryptographic hashing.
[`SourceDigest.lean`](../../tests/formal/lean/PeriScribe/SourceDigest.lean) proves the
shared field encoding injective. The ideal node-hash premise does not prove finite
SHA-256 injective. Reuse also assumes a correctly computed completed receipt; schema
validation cannot establish that an arbitrary forged parent digest is correct.

The [manifest conformance checks](../../tests/formal/conformance/test_source_manifest.py)
execute the actual Lean `SourceManifest.root` with constructor tokens, use executable
Lean field framing, and interpret those outputs with real SHA-256. Inventories of every
length from zero through forty include reversals, changed final leaves, duplicates,
empty fields, Unicode and embedded zeros. They compare the actual iterative Python
composition both without storage and across persistent reuse. An independent recursive
ordinary reference checks the same range of tree sizes. These executions connect the
definitions to those concrete cases; they do not prove arbitrary Python execution or
the iterative tree construction for every inventory size.
Input-key conformance additionally hashes the actual executable Lean fixed-pair framing
for all 124 inventories. Ordinary regressions require exact completed-root hits to avoid
branch reads, malformed receipts to recompute, changed final leaves to reuse unchanged
branches, and completed-root replacement to retain only the current receipt.

# Scoped source authentication

`ParallelSourceAuthentication` extends the fresh-inventory boundary with two independent
workers and sources. Each source can change once. Workers can finish, fail or stop after
cancellation; ownership can expire or move to a different process before admission. A
complete join precedes the caller's admission decision. Invariants reject worker-side or
partial publication, admission before joining, stale stamps, failed reads and dead or
foreign owners. Cleanup follows a completed join. This is a finite safety check, with no
claim that an unresponsive operating-system read eventually returns.

The implementation maps each modeled worker to a strided batch of full byte reads.
`read_inventory_batch` produces local evidence only; `read_inventory_evidence` bounds
workers, cancels remaining work after a failure, and joins every future before returning
or propagating the original exception. `publish_inventory_evidence` validates all current
stamps and owner liveness before one pending-dictionary update. Ordinary regressions must
check actual thread lifetimes, cancellation, process checks before locks, mixed readers,
duplicate paths, symlinks and serial tiny inventories. These adapters retain the original
canonical admission policy and source-generation digest framing.

[`conformance/test_parallel_source_authentication.py`](../conformance/test_parallel_source_authentication.py)
replays every exported edge with its complete shortest checked prefix, using isolated
real byte reads, timestamp-preserving edits, actual expiry/process checks and pending
publication. It requires successful publication as well as rejected admission, failed
reads and cancellation to occur. The finite join maps to completed synchronous batch
calls; ordinary regressions independently hold actual workers across failure and caller
interruption to require joining before exception propagation and enclosing scope cleanup.

`SourceAuthentication` models the checksum evidence used by
`sources.authentication.scope`, `file_digest`, and inventory authentication. A new
preparation scope reads complete
bytes even when an earlier invocation observed matching metadata. Within a live owning
scope, an exact filesystem stamp permits sharing that completed evidence with generation
creation, parsed-cache synchronization and authenticated parsed reads.

The finite configuration contains one source, two content revisions, two edits, two
owning scopes and up to four checksum requests. It retains old evidence after scope exit
to expose cross-scope mistakes independently of the implementation's eager cleanup.
Invariants require every returned checksum to describe the consumed bytes, live evidence
to match its stamp, and expired or differently owned evidence to be ineligible for reuse.

`conformance/test_source_authentication.py` consumes the complete freshly checked graph.
Its adapter replays every actual transition with a complete admitted prefix, using real
temporary files, scope entry/exit and byte hashing. Every modeled edit changes equal-sized
bytes while restoring modification time. Returned SHA-256 values and the number of real
byte reads must match the checked model's answer and hash counter. No handwritten Python
translation supplies the expected cache policy.

Inventory authentication can defer canonical path admission on its first byte read.
That read still compares complete filesystem stamps before and after hashing. The
resulting pending evidence is never returned from storage directly: another request
must use ordinary authentication, resolve its current path inside the owning source
directory, and match the current complete stamp before borrowing it. Repeated inventory
requests also use that admission path. Pending and admitted representations therefore
implement the same checked `Authenticate` transition for modeled owned files; they add
no externally visible publication step. Conformance alternates the two entry points
over every checked history. Outside paths, symlink retargeting, concurrent requests,
copied contexts, and process ownership remain concrete adapter obligations checked by
ordinary regressions.

The model assumes stable bytes during one checksum operation and reliable change
metadata. Production additionally compares stamps before and after hashing and rejects a
changed operation. Its scope closes under the checksum lock, waits for admitted hashes,
and expires copied contexts through a shared live-event token. Ordinary regressions
exercise mid-read mutation, replacement, nested scopes, copied contexts, process ownership
and concurrent readers. Arbitrary external edits that defeat input ownership and reliable
metadata, SHA-256 collisions and filesystem implementation defects are outside this
guarantee. Cooperating pipeline writers retain the existing year lock.

Merkle branch persistence uses the existing product-cache transaction and checksum
contract. `SourceManifest.lean` proves that ordered trees retain every leaf under an
explicit collision-free, domain-separated node-hash premise and that exact matching
child identities permit branch reuse. This ideal premise is not an unbounded claim that
finite SHA-256 is injective. Python checks exercise the actual byte framing and compare
iterative composition with an independent recursive tree construction.

[`conformance/test_source_manifest.py`](../conformance/test_source_manifest.py) evaluates
the actual `SourceManifest.root` definition with a constructor-token projection and
the actual proved `SourceDigest.fields` encoding. Its adapter maps source strings to
exact table identities and interprets the returned tree with real SHA-256. Inventories
of all lengths zero through forty include ordering changes, changed final leaves,
duplicates, empty fields, Unicode and embedded zeros. The checks exercise uncached roots
and successive persistent branch reuse. The recursive input-tree construction and byte
hashing adapter remain implementation obligations checked on these concrete cases;
there is no unbounded proof of Python's iterative tree construction or SHA-256.

Persistent reuse assumes correctly computed completed branch receipts protected by the
existing product-cache transaction and checksum contract. Decoded schema checks reject
malformed entries but do not certify arbitrary forged, well-formed parent values.
An exact complete-input root receipt uses that same contract. `SourceManifest.lean`
proves that flattening fixed path/checksum pairs followed by `SourceDigest.fields`
retains the entire ordered input before hashing. Input-key conformance executes those
actual definitions for all 124 inventories and compares their SHA-256 with Python's
complete-input key. Whole-root receipt selection additionally assumes cryptographic key
collision resistance and a correctly computed completed receipt.

A completed-root hit skips leaf hashing, branch decoding and branch serialization.
Every invocation still authenticates O(B) authoritative bytes and encodes the O(S)
ordered path/checksum fields. On a completed-root miss, composition visits every leaf
and branch and serializes the current branch receipts. The O(D log S) changed-ancestor
hash bound assumes stable tree topology and describes internal hashing on that miss.

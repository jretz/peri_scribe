# Sharing immutable attribute strings

Authenticated parsed-cache documents retain independent mutable dictionaries and lists.
Their immutable keys and string values can share storage across documents without
changing ownership. Each feed transaction owns a bounded string pool; no application
source file or persisted cache encoding changes.

## Complexity assessment

History/state scores 1 for a transaction-local memo. Rule interaction scores 1 for exact
string lookup and admission limits. Mathematical reasoning scores 1 for identity
memoization. Scale/representation scores 2 because immutable sharing reduces decoded
object size while containers retain separate ownership. Failure/concurrency scores 0:
the synchronous decoder introduces no durable transition or concurrent publication.
Total 5 is involved.

## Contract and correctness

The JSON object hook replaces each key and native string with an exactly equal string
already owned by this feed's pool, or retains the supplied value. Lists are visited to
share their string leaves; nested objects have already passed through the object hook.
No dictionaries or lists enter the pool. The caller-owned deep copy still separates
each row's mutable attributes from the reader's validation template and every other row.

For example, two documents containing `{"state": "CA", "values": ["CA"]}` share
the key and string leaves. Changing one row's `values` list or replacing its `state`
does not modify the other row or the fingerprint template. Booleans, integers, floats,
signed zero, null, container order and Unicode spelling retain the JSON decoder's exact
values. Hash collisions do not authorize a hit: Python's dictionary also compares the
complete native strings.

The existing `SourceProvenance.result_equals_derivation` theorem was checked before
implementation with identity as the pure derivation. A pool maps only a string to an
equal string, so every lookup satisfies the theorem's valid-memo premise. Admitting an
identity result preserves validity; refusing admission leaves the valid memo unchanged.
The generic per-call theorem applies even after admission stops. Executable Lean memo
results connect concrete string traces to the same ordered identity results. Native
string equality, Python dictionaries and object ownership remain adapter obligations.
Container independence and bounded admission have concrete regression checks. No new
durable protocol is introduced.

## Costs and limits

The pool admits at most 65,536 distinct strings of at most 256 characters. These limits
bound the pool's reference/index overhead; misses always decode normally. String storage
is bounded by the admitted count and length, with Python's variable Unicode width and
object overhead. Pool ownership ends after the feed's decoded payloads are constructed;
only string references held by actual rows/templates survive.

For K decoded key/string occurrences and L total input characters, decoding and hashing
take O(L+K) expected time under ordinary dictionary assumptions. The pool has O(C)
entries for C admitted distinct strings; every row still owns its dictionary and nested
lists. An explicit list stack retains at most A references for A arrays in one decoded
document, avoiding an additional Python recursion limit. Adversarial collisions or deep
JSON retain Python's usual decoder limits. The pool is
not a global registry or a bound on all source-read memory.

A read-only inventory found about 198 MiB of repeated key objects and another 62 MiB of
repeated short string values across the saved feed dictionaries. This is an upper-bound
estimate before pool capacity, existing intra-document sharing and allocator effects;
the complete pipeline benchmark measures actual resident-memory impact.

## Implementation and verification

`geo.attribute_strings.AttributeStrings` owns the pool and JSON object hook;
`geo.dictionaries.decoded_payloads` creates one pool per feed read. Ordinary tests check
Unicode, duplicate keys, nested arrays, scalar distinctions, capacity fallback and
independent row mutation. Formal conformance compares the actual pool's string traces
with the checked generic Lean memo oracle. Complete pipeline output comparisons remain
the acceptance check for published content.

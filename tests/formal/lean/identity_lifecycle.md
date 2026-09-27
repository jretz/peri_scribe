# Complete identity allocation and persistent history

`IdentityLifecycle.lean` extends `Identity.lean` through all allocation phases and
successive acknowledgements. Its 27 theorems and `OracleOwnership.lean` share the
definitions executed by `oracleOwnership`. The Python owners are
`fire_updates.history_claims`, `resolved_ownership`, `prepare_updates`,
`acknowledged_state`, and `write_updates`. The complete allocation model covers the
compatible existing-ownership domain described below; the
[history transfer model](identity_transfer.md) covers competing current claims.

## Complete allocation

The reference resolves existing identifier aliases first, including direct historical
perimeter keys when an alias binding is absent. It next resolves the complete batch of
name-only claimants against eligible unreserved histories, then identified claimants
against the remaining histories. Both phases use `Identity.candidates` and
`uniqueOwner`, including mapping/source continuity, local aliases, preferred local
owners, and competing claimants. Finally it assigns every unresolved fire an unused
requested or fresh key.

The proofs establish that:

- Each phase retains existing ownership and has a supporting candidate when adopting.
- Its new reservations cover all adopted owners, excluding them from later phases.
- The complete resolver preserves unique ownership under the initial ownership
  assumptions below, assigns every current fire, and retains known identifier owners.
- Name-only adoption cannot be replaced by a later identified claimant or allocator.
- Fresh allocation cannot reuse any reserved historical or current key.

The allocator models a local identity as an opaque fresh natural number. Python uses
a SHA-256 digest of report identity, mapping signatures, and reservations. The bridge
binds every existing or direct requested key exactly. A model-generated fresh identity
must correspond to a distinct Python local key that was not reserved, and both
reversed input order and repeated execution must return identical actual keys.
The proof does not establish collision-freedom of arbitrary SHA-256 inputs.

The oracle receives the raw checkpoint's aliases, perimeter keys, history names,
signatures and sources, plus all current claimants. The adapter expands legacy
name-shaped keys into normalized input names and serializes raw aliases; it never
calls the production stable-identity or candidate-selection helpers to obtain expected
owners. Current records are serialized in Python's canonical report-key allocation
order. The model itself applies identifier lookup, both adoption phases, and allocation.

Conformance covers 5,048 complete batches derived from the existing continuity
catalogue with varied mixtures of name-only and identified fires, known owners,
legacy direct keys, reserved historical aliases, local preferences, rename evidence,
empty histories, source corrections, and ambiguous claims. Every batch also runs the
actual resolver with reversed insertion order and as an unchanged retry.

## Acknowledged evidence and real publications

The acknowledgement model accumulates evidence independently for each stable owner.
Membership is exactly the union of previous and current evidence, so arbitrary later
publications preserve history, including owners absent from the current input. Repeating
an acknowledgement is idempotent in membership. New mapping is characterized by the
existence of a current signature absent from the previous history, equivalently by
acknowledgement increasing the evidence set.

Alias updates replace only the supplied alias and preserve other bindings. Every
resulting association has a source in the current or previous checkpoint. Aliases
that are either absent or consistently reaffirmed in each later publication retain
their owner through an arbitrary publication sequence.

The bridge exercises three multi-publication scenarios in both input orders, totaling
40 persisted publication rounds. These include corrections retaining a source reference,
identifier enrichment, identified renames, a newly mapped namesake, competing name-only
and identified claimants, and disappeared/reappeared fires. Real Type 1 fire objects
pass through actual report selection, `prepare_updates`, `write_updates`, state
serialization and reload, monthly JSONL journals, and validated log reading. No report
or storage operations are mocked.

For every round, complete owner selection comes from `resolve`; each perimeter/source/
name evidence set comes from `acknowledge`; aliases come from `aliases`; and expected
record identities come from `novel`. The checks compare every state field, retain all
previous log entries and all new record contents, and require two writes of the same
prepared batch to leave the log unchanged. In these fixtures, preparing unchanged input
after publication produces no further records. Reversing the current input preserves
state and the complete set of prepared records. The retry guarantee concerns a frozen
prepared publication: recomputing claims after newly learned alias lineage is a new
resolution and is not the same idempotency statement.

These checks use actual geometry/time signatures as opaque evidence tokens. Their
cryptographic identity and real-world fire truth remain separate boundaries. The
publication fixtures make every mapped fire interesting through Type 1 selection, so
the `novel` predicate is sufficient for record eligibility there; it does not model
all report-section admission policies.

## Input assumptions and limits

The unique-ownership theorem requires existing identifier bindings for distinct
**current** fires to resolve to distinct historical owners. A valid earlier checkpoint
may associate aliases `a` and `b` with one history while a later input splits them
between two current fires. This existing model does not establish uniqueness for that
case. The checked allocation and publication fixtures satisfy the stated premise.

The [history transfer model and conformance](identity_transfer.md) cover those competing
claims and unions of multiple histories. They separate a durable bucket from its current
claimant, select the latest mapped observation with deterministic ties, and allow later
corrections to reverse ownership. The original allocation theorem retains its narrower
input premise; the transfer guarantees apply to the expanded ownership policy.

Similarly, consistent alias updates are an explicit premise of the persistent alias
theorem. General alias reassignment has a source, but is not proved to preserve its
former owner. Production compatibility aliases can now change owner; the separate
transfer model proves that durable alias lineage retains every earlier route. Current
report identities are distinct, and name normalization and external source identity are
trusted inputs to this model. Competing identifier groups and cryptographic collisions
are outside the original allocation guarantee.

The persistence proofs concern retained evidence membership and associations. Atomic
file replacement, crashes, journal recovery, and rotation have their own TLA+ models
and conformance tests. Passing this finite bridge is not a proof that every Python
execution refines the unbounded Lean model.

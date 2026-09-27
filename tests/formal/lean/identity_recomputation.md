# Recomputing history ownership after acknowledgement

`PeriScribe/IdentityRecomputation.lean` proves the complete ownership feedback fixed
point for arbitrary finite numbers of current fires and historical buckets. Its 43
checked theorems reuse `IdentityTransfer.latest` and `chooseWriter`; an explicit
refinement theorem equates its aggregated claimant executor with
`IdentityTransfer.claimant` over the same complete route sets.

The argument derives stability rather than assuming it. Writer allocation is injective
because each selected existing bucket has one winning claimant, and fresh keys are
unused and distinct. Learning retains the old claims and adds the histories whose
resolved owner is that fire's writer. Every old winning claimant therefore survives
learning; any new winning claimant already has that writer as the resolved owner.
Each writer consequently wins its own bucket on recomputation. Saving that writer as
the preference makes the next allocation select it, and the complete owner function
remains unchanged, including unclaimed histories and old chains or cycles.

Induction establishes writer, owner, and learned-route stability after any number of
unchanged retries. Separate theorems prove exact per-alias learning under nonempty,
disjoint current alias groups, and stability of every learned alias route. Historical
route overlap is unrestricted. Acknowledgement preserves original evidence buckets;
repeated acknowledgement adds no evidence, and the current mapping is never novel on
an unchanged retry. The acknowledgement result applies independently to perimeter,
source, and name evidence represented as opaque tokens.

The executable oracle materializes finite functions to avoid repeatedly evaluating
prior checkpoints. Lean proves this executor equals the original feedback definitions,
including its repeated execution and evidence records.

The same feedback protocol is also checked by `tla/IdentityRecomputation.tla`. Its
phases are resolution, alias learning, evidence acknowledgement, and resolution of the unchanged
fires from the new checkpoint. Current fires have distinct report identities and
disjoint alias groups, as supplied by source grouping. Each model fire represents the
union of the historical routes through its current aliases. Arbitrary overlap between
those historical route sets remains allowed. Priority is a fixed total order obtained
from latest mapped observation time and the report-key tie breaker.

The model computes winning claims, preferred-or-minimum writer selection, fresh
allocation, direct ownership including self-owned writers, learned routes, and evidence
acknowledgement. It checks writer uniqueness, evidence retention, stable writers and
owners after recomputation, closure of learned routes, and absence of newly reported
mapping on the retry. Initial owners may form chains and cycles. Lineage may overlap
or be empty, and preferred keys may belong to a losing claimant.

The main configuration explores two current fires and three old history buckets, with
27,648 initial states and 31,698 distinct reachable states. Two unused symbolic keys
represent fresh allocation. The bridge configuration uses two old buckets and has
576 initial states and 873 reachable states. A third configuration checks three current
fires and two old buckets, including simultaneous losing claimants allocating distinct
fresh writers; it has 6,912 initial states and 9,363 reachable states.
There is no fairness or crash assumption:
this is a safety check of the pure feedback sequence. Existing journal models cover
interruption between durable publication effects.

## Connection to the implementation

`conformance/test_identity_recomputation.py` follows complete exported TLC edges. It
constructs raw `State` instances and runs the actual `resolved_ownership`,
`acknowledged_state`, checkpoint write/read, and fresh resolution. Every checked
writer, owner, alias-route union, preference, and evidence set is compared with the
corresponding model state. Acknowledging the recomputed result must equal the entire
restored production state, and each current signature must already be inherited.

The bridge exercises all 256 representable initial states in its configuration.
Persisted preferred aliases necessarily contribute their own history route; the other
320 abstract initial states violate that serialization relationship and are checked by
TLC without being passed to Python. Each current fire carries two external aliases;
the alias groups are disjoint while their claimed history sets can overlap. Dates and
real geometry signatures remain separate from model tokens.

`conformance/test_identity_recomputation_large.py` also compares complete executions
with `oracleIdentityRecomputation`. It runs 96 input scenarios at sizes zero, one,
three, five, eight, 16, 32, and 64 current fires, with up to 195 historical buckets.
Each fire has two external and two component aliases. Six route patterns exercise
interleaved overlap, nested claims, partitions, alternating shared sets, adjacent
chains, and empty claims requiring allocation. Owner maps include partial mappings,
long chains, and cycles. Dates include missing observations, negative and zero Unix
times, multiple observations, and equal-date lexical ties. Preferences can lose.
Reserved report keys force SHA-derived local writer allocation in the fresh cases.

Every scenario runs four actual resolution/acknowledgement/checkpoint-round-trip
cycles, with reversed current-fire input on retries. All 384 complete observations
compare writers, every history owner, learned routes, acknowledged mappings, and
novelty with the executable proof. The entire Python checkpoint must remain equal after
its first acknowledgement, including individual aliases, source evidence, and names.
The actual `prepare_updates` coordinator must then return no records and the same
checkpoint. Initial complete claims come from the separate alias-transfer oracle,
using raw saved aliases and lineage, before entering the feedback executor.

## Boundaries

Current report identities are distinct, alias groups are nonempty and disjoint, and
current fires, mapped priority, and evidence stay unchanged during retries. Every
initial claim lies in the enumerated historical domain. Alias learning includes the
complete claims and final inherited histories. These are explicit input/representation
premises, not assumptions that the resulting writers are stable. The model proves the
current alias-group aggregation from those premises.

Fresh allocation is abstracted by distinct unused tokens. The oracle's total fresh
function extends the finite supplied fresh keys with a disjoint range above every known
key. The bridge takes fresh opaque keys from actual allocation, checks their unused and
injective domain independently, and supplies them as fresh tokens. Existing writer
selection still comes from Lean. The queried owner domain must equal the raw retained
buckets plus allocated writers, so omitted buckets cannot disappear from comparison.
Neither proof establishes cryptographic collision resistance. The larger bridge
exercises both unused report keys and SHA-derived local keys. Future symbolic fresh keys
are unused; the proof shows no allocation is needed on an unchanged retry.

Routes and historical domains are compared by membership, matching Python frozensets
and dictionaries. Concrete list order or multiplicity is not persistent state. Name-only
continuity adoption and source component identity remain separate contracts: this
feedback model starts from their complete claims, and the larger bridge uses identified
fires with component aliases. Corrections changing current fires, priority, or evidence
can deliberately change ownership. Filesystem crashes and pending-transaction recovery
remain covered by the separate journal models and execution traces.

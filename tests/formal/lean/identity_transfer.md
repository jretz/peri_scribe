# Correctable ownership of durable fire histories

`PeriScribe/IdentityTransfer.lean` has 56 checked theorem declarations. Its default
`oracleIdentityTransfer` executable evaluates the same definitions, and the shared axiom
audit includes the module. The implementation owners are
`fire_updates.{history_lineage,history_claims,mapping_priority,resolved_ownership,
prepare_updates,acknowledged_state}`, `updates.snapshot_from_entries`, and projection in
`updates.html`.

## History identity and current ownership

A durable history key identifies a saved evidence bucket and the immutable identity in
its original log records. These keys reflect previous grouping and allocation decisions;
two different keys do not establish that two different physical fires existed.

Current ownership is a separate, direct mapping from each durable bucket to its current
writer key. Identifier lineage records every durable bucket reachable through an alias.
Lineage is preserved when ownership changes, so a later correction can claim a bucket
again. Names, source references, and perimeter signatures remain evidence in their
original buckets. Reassigning ownership does not move or delete those records.

The model keeps a current report identity separate from its selected durable writer key.
A claimant reaches the union of every history associated with its aliases, plus
explicitly supplied direct-key fallback, name adoption, or fresh allocation. Each bucket
independently chooses the greatest claimant by:

1. A dated mapping outranks an undated mapping.
2. Later mapped observation time outranks earlier time.
3. Equal times use the greatest report identity in deterministic lexical order.

The bridge encodes sorted report identities as ordered natural tokens. Time is an
optional integer, admitting dates before the Unix epoch. The production priority uses
the latest dated, nonempty perimeter observation from each current fire. It is not
publication completion time or alphabetical input-list position.

The winning fire keeps its preferred writer key when it won that history; otherwise it
uses the least won key. With no won history, the existing allocator supplies a fresh
key. The writer-selection proofs establish membership, minimum selection, and the exact
condition for requiring allocation. Injective writer assignment preserves distinct
current groups. Unclaimed buckets retain their previous owner.

## Proved guarantees

Reachability has an exact alias-or-explicit-history witness. Every selected claimant is
an input fire that reaches the bucket and dominates all competing claimants. Priority is
reflexive, transitive, and total, and equivalent priority identifies the same report
key. Consequently, winner identity is independent of input ordering, including ties.

The ordered-publication core agrees with the last matching claim, changes only declared
buckets, has at most one current owner per bucket, and permits A-to-B-to-A reassignment.
Repeating a fixed claim sequence or frozen prepared publication is idempotent. Complete
publication sequences refine a flattened sequence of claims and an accumulated evidence
set. Recomputing claims after learning new alias lineage changes the inputs. The
[recomputation checks](identity_recomputation.md) separately verify that complete
feedback cycle under disjoint current alias groups and derive writer uniqueness from
allocation. The frozen-publication theorem alone does not establish that result.

Acknowledgement membership is exactly old-or-current evidence in the same bucket. Every
old record and every acknowledged new record survives arbitrary later publications.
Ownership decisions are independent of the evidence contents, and evidence retention is
independent of owner selection. Concrete record lists refine that evidence model.

Inherited evidence is exactly the union of all buckets in the final owner map pointing
to a writer, including previously owned buckets unclaimed in the current publication.
Novelty requires a current signature absent from that complete union. Ownership changes
alone therefore do not make previously acknowledged mapping new.

Alias learning retains old lineage and adds original claims, final inherited buckets,
and the current writer key. An unsuccessful claimant retains its route to the histories
it claimed. Reaffirmation is idempotent in set membership. After histories are merged,
the resulting alias lineage can keep them jointly claimable in future corrections:
reversible ownership does not mean automatically reconstructing an earlier partition.

Viewer projection performs exactly one owner lookup per original record. It preserves
record count, payloads, and order, including ownership chains and cyclic swaps. Original
log identities remain immutable. An unowned record keeps its original key. The latest
chronological predecessor across a projected group supplies previous acreage. The
[composed snapshot proofs and bridge](projected_snapshots.md) check exact predecessors,
emitted rows, and time-window filtering under the current owner map. The transfer model
does not sum historical acreage values.

## Executable interface

Commands use pipe-separated sections. Natural-number lists use spaces; record fields use
commas, with colon-separated alias/history lists inside records. `n` represents absent
time, absent preferred writer, or an empty list. Time fields otherwise accept signed
integers. Ownership and evidence records have the form `history,value`; fire records are
`identity,time,aliases,additionalHistories`. Lineage entries are `alias,histories`.

| Operation | Checked result |
| --- | --- |
| `claim` | Maximum claimant for each queried bucket, or `-1`. |
| `transfer` | Final writer per bucket, retaining unclaimed previous owners. |
| `chooseWriter` | Preferred won key, least won key, or `-1` for allocation. |
| `inherit` | All evidence in buckets currently owned by the queried writer. |
| `novel` | Whether current evidence grows that inherited union. |
| `lineage` | Monotone lineage union with an explicit history set. |
| `learn` | Union of original claims, final inherited buckets, and writer key. |
| `ack` | Acknowledged records retaining their original bucket identities. |
| `project` | Ordered record payloads with one-hop current group identities. |

## Implementation conformance

The bridge checks 291 complete identified-fire batches against the compiled oracle.
The 288 generated combinations vary both historical lineage sets, preferred minimum or
maximum writer, distinct or overlapping current aliases, four timestamp patterns,
retained owners, and newer empty geometry. Three additional cases cover legacy direct
keys and histories reserved solely through provenance. Timestamp cases include missing,
negative, zero, and equal times, latest observations before the final input perimeter,
and newer empty geometries that cannot win the priority calculation.

Actual `resolved_ownership` results are compared with `claim`, `chooseWriter`, and
`transfer`, including original claims and every final inherited bucket. Existing keys
are bound exactly; allocated local keys must be distinct and unreserved. Reversed input
order and repeated resolution must agree. Existing lifecycle conformance separately
covers name adoption and fresh allocation in the compatible-ownership domain.

Two persisted scenarios run in both input orders, totaling 26 real publication rounds.
They exercise merged histories, absent aliases returning, splits, ownership reversal,
disappearance and rejoining, optional timestamps, and alias reassignment. Actual report
selection, `prepare_updates`, `write_updates`, state serialization and reload, monthly
JSONL journals, and generated `updates.json` run without mocked selectors or storage.

The oracle checks every accumulated perimeter, source, and name pair, novelty against
the complete inherited union, learned lineage, priority-based compatibility aliases, and
the viewer's one-hop projection. Original journal byte prefixes remain intact. Rewriting
the same frozen prepared publication leaves the journal unchanged; recomputation retries
are also checked for these scenarios, whose current aliases are disjoint. The bridge
does not generalize that latter result to arbitrary overlapping current alias groups.

A third scenario seeds two real histories and sends records with a shared identifier
through `group_fire_record_indices` and `most_common_fire`. The resulting single fire
retains every alias, and publication, journal, viewer, and recomputation checks use the
same oracle. Its two additional rounds bring the total to 28. This tests the real
upstream grouping that supplies disjoint current alias groups to publication.

The browser bridge checks 256 ownership cases: all 64 partial owner maps over three
buckets, across four typed identity layouts. Each runs independent, projected, and
independent grouping again, totaling 768 live DOM states. These include merges, splits,
reversals, chains, cycles, and unowned-record fallback. The `project` oracle checks
actual snapshot groups and unchanged raw payloads; the presentation oracle checks the
shipped JavaScript's group counts, occurrence order, and DOM reuse. A mutation that
ignores `history_identity` is rejected by this bridge. These checks exercise rendering
behavior without claiming to prove the browser or DOM implementation.

## Boundaries

Theorems quantify over arbitrary finite input lists and unbounded integer times. They
assume correctly normalized identity tokens and timestamp values, and lexical token
ordering consistent with the production report and history keys. Cryptographic perimeter
signatures are opaque evidence tokens. Source truth and real-world fire identity are not
proved.

The input to alias learning lists the complete durable-key domain used to enumerate
inherited buckets. Current report identities must be distinct, and writer assignment
must be injective on those identities. Upstream grouping supplies disjoint current alias
groups in the persisted publication fixtures. If synthetic current fires share aliases,
learning a losing claimant's fresh bucket can change the next recomputed resolution;
ownership of any fixed input is still unambiguous. Fresh allocation, existing
name-continuity adoption, source parsing, and filesystem publication protocols remain
separate contracts. Their outputs are supplied explicitly instead of being inferred from
an arbitrary ownership choice.

The projection changes neither raw logs nor bucket contents. Its one-hop owner map is
not an equivalence relation closed transitively: A-to-B and B-to-C sends original A
records to B and original B records to C. This permits corrections and owner swaps
without accidentally moving an entire chain of histories.

Source-derived anonymous identities now satisfy the distinct report-key premise through
[ComponentIdentity](component_identity.md). Its 14 additional persisted rounds pass real
internal component aliases through this same executable transfer, learning, evidence,
novelty, and projection bridge. External identifiers and internal components remain
separate namespaces. Legacy summaries without component metadata retain their name-only
ambiguity; the new guarantee does not infer a missing provenance key from a display
name.

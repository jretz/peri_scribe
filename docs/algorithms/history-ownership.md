# Fire update history ownership

## Contract and context

A fire update compares current mapped evidence with previously acknowledged evidence.
Corrections can move an identifier between current fires. The algorithm assigns durable
history buckets to current writers while retaining the evidence and alias routes needed
for a later correction. A bucket is a stable log identity; it is not necessarily the
current external identifier. This policy spans `resolved_ownership`, `history_claims`,
`acknowledged_state`, and `prepare_updates` in [fire_updates.py](../../src/peri_scribe/fire_updates.py).

Inputs are current fire summaries with distinct report identities, disjoint current
identifier/component alias groups, mapped signatures, and exact source references, plus
the last valid checkpoint. A signature combines normalized geometry and observation
instant. Source grouping supplies identity separation; this algorithm does not repair
contradictory current alias groups. Dates are aware instants; displayed update area uses
the latest mapped geometry in acres, independently of reported incident area.

Outputs are unique writer keys, a direct owner for each retained bucket, learned alias
routes, accumulated evidence, and update records for selected interesting fires. Every
mapped fire advances the baseline, including uninteresting fires. Persistence is the
separate [update journal](update-journal.md) contract.

## Complexity assessment

| Dimension | Score | Concrete reason |
| --- | --- | --- |
| History and state | 3 | A later identifier correction transfers ownership of already acknowledged mapping. |
| Rule interaction | 3 | Several current fires may claim the same retained bucket; namesakes and losing preferences must stay distinct. |
| Mathematical reasoning | 1 | Set unions and deterministic total-order arbitration establish allocation and retry stability. |
| Scale and representation | 2 | Canonical JSON identities, alias routes, and separate evidence buckets must agree across checkpoints. |
| Failure and concurrency | 0 | This assessment covers the ownership transformation; persistence is assessed separately. |

**Total 9: complex.** The published update history also makes explicit novelty and
identity contracts necessary regardless of score.

## Approach and invariants

1. Build complete alias lineage by including saved preferred aliases and retained routes.
   Identified/component fires claim all reachable histories. Histories reserved by known
   aliases cannot be stolen through a name match.
2. Consider remaining legacy name continuity. Require normalized-name agreement and a
   shared mapping signature or exact source reference; empty histories need no mapping
   witness. A match must be unique in both directions. An acknowledged local alias can
   resolve an otherwise recurring ambiguity.
3. Resolve each claimed bucket by the greatest mapping priority: dated evidence outranks
   undated evidence, then latest nonempty mapping time, then report identity. Iteration
   order cannot decide a winner.
4. Give each fire its preferred writer if it won that bucket, otherwise its smallest won
   key. A fire winning nothing gets an unused report key, or a deterministic local digest
   when its report key or normalized name collides. Reserve each allocated key immediately.
5. Save direct owner assignments and make every current writer self-owned. Keep original
   evidence in its original buckets. Learn both losing claims and inherited histories
   through each current alias; append new evidence only to the current writer's bucket.

![Two claimants and a later correction](assets/ownership-claims.svg)

*The shared bucket has one current owner, while both routes remain available. The second
panel changes mapped priority, not the stored evidence, to illustrate a legitimate transfer.*

Writer uniqueness follows because each won bucket has one winning fire and each fresh
allocation reserves an unused key. Unioning evidence into a writer does not erase old
buckets. Retaining losing routes is essential: overwriting lineage with only the winning
route would prevent a corrected fire from reclaiming its own earlier history.

For unchanged inputs, a current writer wins its own bucket on recomputation. Learning
adds histories already owned by that writer while retaining its old winning claims;
saving the writer as the preference therefore chooses it again. Evidence unions are
idempotent, so acknowledgement reaches a fixed point: resolving again gives the same
writers and owners, with no novel mapping. Old owner chains or cycles are retained as
data but are not recursively chased as the current assignment.

## Worked examples and boundaries

Suppose bucket H contains signature p and is reachable through aliases of fires A and B.
A's latest mapping is 10:00, B's is 11:00. B wins H; A receives a distinct writer. Both
claims remain in lineage. A later correction gives A a 12:00 mapping, so A can win H
again. Copying all inherited evidence into every claimant would make both appear to have
acknowledged p and destroy the meaning of single ownership.

Two unrelated fires named Pine with no shared mapping/source witness remain distinct.
Even a matching name and signature is insufficient if two current candidates claim the
same legacy history. A formerly uninteresting fire becoming interesting with unchanged
mapping produces no update: selection does not erase its earlier acknowledgement.
A fresh survey with the same geometry can produce a new signature when its observation
instant changes. Empty latest geometry suppresses an update record.

## Costs and limitations

Let F be current fires, H retained buckets, C total expanded claims, A aliases, and E
retained evidence tokens. Priority ordering costs O(F log F); claim traversal costs at
least O(A + C). Current per-fire scans over winners/owners and name candidates can cost
O(FH), with set-intersection work depending on evidence sizes. Checkpoint storage is
O(H + A + C + E); historical evidence is deliberately retained and is not bounded by a
fixed number of recent updates. Geometry signature calculation adds geometry-byte cost.

Stable retries assume unchanged current identities, priority and evidence, valid
canonical identity encodings, and collision-resistant local digests. The algorithm does
not establish source truth, identify arbitrary namesakes without evidence, or make the
journal atomic. Input assumptions and SHA-256 collision resistance remain explicit.

## Implementation and verification

- Ordinary checks: [ownership](../../tests/tests/standard/peri_scribe/test_fire_updates_ownership.py),
  [transfer](../../tests/tests/standard/peri_scribe/test_fire_updates_transfer.py),
  [corrections](../../tests/tests/standard/peri_scribe/test_fire_updates_corrections.py), and
  [identity](../../tests/tests/standard/peri_scribe/test_fire_updates_identity.py).
- [Ownership recomputation inventory](../../tests/formal/lean/identity_recomputation.md)
  connects Lean's finite-input fixed-point proof and bounded TLA+ feedback model to the
  complete resolver, acknowledgement and persisted checkpoint round trip.
- [Recomputation conformance](../../tests/formal/conformance/test_identity_recomputation.py)
  and [larger cases](../../tests/formal/conformance/test_identity_recomputation_large.py)
  compare writers, owners, learned routes and evidence with executable formal results.
  Name-only adoption and concrete geometry signatures have separate tests; abstract
  evidence tokens do not verify geospatial measurements.

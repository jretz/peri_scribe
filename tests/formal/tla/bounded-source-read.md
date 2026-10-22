# Bounded source-reader lifetimes

`BoundedSourceRead.tla` covers the catalog lease and complete-stage boundary owned by
`geo.catalog.open_catalog`, `fires.bounded_sources.prepare_groups/build_rows/build_fire`
and `fires.files.build_bounded_full_geography/write_bounded_full_geography`.
A pinned metadata inventory is followed by global ownership resolution, detailed block
work, final authoritative-source validation, reader release and full-history publication.
The existing ordered-worker model separately covers pending count/weight admission and
ordered result delivery; this model counts active detailed computations.

The finite configuration has two blocks, at most two active computations, two source
revisions and independently poisoned blocks. Edits can occur once at any point,
including after validation. Poisoning precedes pinning and represents malformed metadata,
attributes or geometry in the disposable parsed cache. Checked invariants require
verified blocks before completed work, complete work before publication, an authenticated
pinned revision, ownership before work and settled workers before resource release.
The model makes no liveness or deadline claim.

## Concrete observations

The conformance adapter retains every variable and follows one continuously matched path
in TLC's freshly checked complete graph. It uses a real SQLite catalog containing two
independent fire observations, real source-file checksums and pinned read transactions,
actual grouping/ownership, source hydration, classification and history reconciliation.
The success path writes a real full-history GeoPackage and authenticates its published
signature. Wrappers observe existing production calls; they do not choose admission,
verification, fallback or publication outcomes.

| Model variable or action | Concrete observation |
| --- | --- |
| `revision`, `Edit` | Authoritative source bytes differ from their original contents. Before-pin edits also update the fixture's valid parsed-cache receipt. |
| `pinned`, `Pin` | Feed connections have opened; the metadata read receives the captured source checksum. |
| `Metadata` | Real metadata authentication returned records without coordinates or attribute documents. |
| `Ownership` | Real ownership/grouping returned the exact two singleton groups. |
| `bad`, `Poison` | Actual SQLite metadata or payload bytes were corrupted before the read lease opened. |
| `running`, `Admit` | A real block worker entered its detailed calculation. Both workers must overlap. |
| `checked`, `Verify` | Real hydration returned exact expected source rows while the invocation still accepts results. |
| `complete`, `Finish` | Real reconciliation returned complete output rows before any invocation failure. |
| `Validate`, `validatedRevision` | The catalog's real final inventory/checksum validation succeeded for its pinned revision. |
| `Release` | The actual context exited and every SQLite reader rejects further queries as closed. |
| `published`, `Publish` | The actual output exists and its full-layer signature authenticates successfully. |
| `Abort`, `Settle`, `Fallback` | A production operation raised, remaining workers returned, readers closed and no full-history output was published. |

After the first failure, another worker can finish authentication or computation while
its executor is being joined. That work is abandoned: the projection records `Settle`,
without adding it to the invocation's accepted `checked` or `complete` sets. Queries
inside the delayed worker verify that its real SQLite lease remains open until it exits.
`Fallback` means this bounded attempt has safely relinquished its resources. Parsed-cache
unavailability returns `None` for the complete-source adapter; a changed authoritative
source raises `OSError` for the caller to handle. The model abstracts those distinct
caller outcomes into the same terminal resource state.

The concrete corpus uses both worker completion orders, source edits before pinning and
after each observed lifecycle boundary, and all nonempty poison subsets for metadata,
ownership attributes and geometry. Metadata and attribute corruption fail before work;
singleton grouping lets geometry corruption reach the detailed worker's actual decoder.
Worker gates control timing only; decoded data, checksums and output rows remain real.

## Limits

The model authenticates the generation that passed final validation. A source edit after
that validation may precede publication, and the model permits publication of the already
validated pinned generation. It does not claim that output always reflects the latest
source bytes at the instant of replacement. Existing generation identities allow later
invocations to detect that change.

Checksums are treated as collision-free identities. The model abstracts SQLite snapshot
isolation, exact geometry numerics and the shared payload codec; their existing ordinary
and formal checks remain applicable. It does not establish byte-weight or RSS bounds,
power-loss durability, the correctness of arbitrary source parsers, or atomic replacement
of multiple output files. Existing geography publication and authenticated-reader models
cover those distinct boundaries. This adapter does not model complete-source fallback's
subsequent work, only safe abandonment of the bounded attempt.

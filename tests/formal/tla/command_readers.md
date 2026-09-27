# Command writers and geography readers

## Every authoritative command owns the year

`SourceWriters` extends the existing run-only exclusion and recovery checks to the
`validate-sources` command. The public CLI audit covers `main.Commands.list_commands`:
`run` and `validate-sources` can change authoritative source data. `monitor`,
`show-latencies`, `show-colormap`, and `version` are observers. Command log files are
outside the authoritative source/geography contract. `pipeline.fetch_external_source` is
an internal helper called within `run`, not a registered standalone command.

The model maps to `pipeline.run`, `pipeline.validate_sources`,
`pipeline.validate_locked_sources`, and `pipeline_state.run_lock`. It checks two
competing writers, changed and unchanged source results, all pending/forcing Boolean
inputs, and one interruption per writer. The 3,398-state graph proves exclusive
ownership, mark-before-mutation, and preservation of rebuild intent whenever sources
differ from completed outputs. Its pending Boolean abstracts the nonempty set of
required derived stages. Existing run-state models check individual stage sets and their
acknowledgments.

Validation acquires the same nonblocking exclusive year lock as `run`. It collects its
isolated reference snapshots first, then records every derived stage before its
incremental fetch can mutate authoritative sources or rebuild their index. Successful
unchanged collection restores the exact prior pending state and forcing flag. Changed
collection or interruption leaves rebuild requirements for a later `run`. Validation
never acknowledges completed downstream output. Existing deferred-input intent remains
intact throughout validation.

`test_source_commands.py` connects TLC's validation outcomes to all 32 concrete pending
stage/forcing combinations. It executes unchanged, changed, and interrupted collection
for each, including unchanged retries after interruption. Its CLI inventory assertion
requires reconsidering the writer audit when new public commands appear. Ordinary
regressions were confirmed failing before implementation: validation could fetch while
another writer owned the year, and source writes had no durable rebuild requirement.

The model assumes atomic recovery-marker replacement and eventual filesystem visibility
of completed writes. It is a safety check, not a guarantee that another invocation will
run or successfully rebuild. Clients that directly call unlocked implementation helpers,
external file modification, adversarial lock-file replacement, and power loss remain
outside this contract. The existing run liveness checks cover progress under their
stated future-invocation and failure bounds.

## Successful geography reads use one generation

`GeographyReaders` models full-file replacement, full-signature replacement,
differential-file replacement, and differential-signature replacement as separate
transitions. A writer can stop after any transition. An independent reader acquires a
shared year lock, authenticates both files and their relationship, then reads incident,
full perimeter, point, and differential perimeter layers before releasing the lock.

The 1,838-state graph starts from 162 combinations of absent/old/new file bytes and
absent/old/new metadata, with strict or tolerant reads. Metadata is produced by the
checked writer: a differential signature's content identity and full-history dependency
belong to the same published generation. Forged matching signatures and hash collisions
are excluded. The invariants prohibit competing reader/writer ownership, unauthenticated
row reads, and mixed-generation results across the separately opened layers. There is no
liveness claim for a permanently missing or mismatched pair; refusal is the safe result.

The implementation mapping is `pipeline_state.read_lock`,
`fires.derived_layers.authenticated_pair`, `read_locked_derived_layers`, and
`read_derived_layers`. Full and differential signatures must match the current bytes and
required layer declarations. The differential generation must equal
`fires.differential.differential_generation` for that full checksum and the current
derivation context. Thus changed derivation code or context also requires geography to
be rebuilt before downstream reading. Authentication runs before execution-cache lookup;
the cached layer identity includes both authenticated checksums.

A standalone reader refuses immediately while another writer owns the year. The owning
writer may read its completed pair in the same process, thread, and live context without
reacquiring a conflicting shared lock. Copied contexts cannot retain this permission
after the writer releases its lock or transfer it to another process or thread.
Additional readers may share a read lock, but another writer cannot change either file
between layer reads. As elsewhere, low-level helpers require their documented
caller-held lock.

Tolerant scoring preserves the fresh-year case only when **both** geography files are
absent. A partially present pair raises a missing-file error. Present files with
missing, invalid, or incompatible authentication require rebuilding geography; unsigned
legacy pairs are not silently accepted. The raw `read_incident_layer` adapter remains
available for older standalone GeoPackages without an incident layer, returning empty
history for that absent layer. It does not claim a cross-file generation guarantee.

`test_geography_readers.py` maps all 162 checked authentication inputs to actual
GeoPackages and separately copied signature files. All now follow continuous TLC paths
through actual locks and each returned layer. Twenty additional writer-prefix/read
histories continue from actual publication into authentication after release, including
interrupted mixed pairs. Successful reads compare all four layer payloads with the
expected generation. The [execution extension](../execution_paths_extensions.md) also
documents 44 publication/recovery histories with real generation reuse, separate
file/signature writes, coordinator acknowledgment, and a subsequent source generation.
Ordinary tests attempt another writer at every layer boundary, test nested-owner and
competing-reader behavior, and verify that expired or transferred ownership cannot
bypass exclusion. The mixed-generation regression was confirmed failing before the
reader fix: replacing only full geography left the reader able to return new full rows
with old differential rows.

`GeographyPairExpected` remains a valid counterexample about **physical files**: they
are still published one at a time and can differ after interruption. The new reader
contract prevents that physical intermediate state from becoming a successful downstream
result. Direct unguarded file readers do not gain this guarantee. Filesystem locking and
atomic single-file replacement retain the common process-interruption assumptions; this
is not a power-loss durability proof or a verified GeoPackage serializer.

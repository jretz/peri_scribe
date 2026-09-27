# Complete incident histories

`PeriScribe/IncidentHistory.lean` extends the local `Reconciliation` rules through
arbitrary histories of arbitrary fields. The executable reference sorts by observation
clock, direct-feed priority, snapshot serial, and filename, selects one source for each
simultaneous field, and applies independent confirmation ledgers across the whole
history. Field zero denotes incident acreage; all other fields use the non-area rule.

## Guarantees

- A simultaneous winner retains an entire source record. Matching values keep the newest
  available formal confirmation, and conflicting values follow source priority.
- Reconciliation emits only fields present at that instant. Every resulting value has a
  source observation for the same field at or before that observation time; no value can
  leak from another measurement's ledger.
- Confirmation ledgers change only on a confirmed, dated report of that field. An
  omitted field, an unconfirmed edit, or a report without a confirmation date cannot
  reset it.
- Stale unconfirmed non-area edits preserve the ledger value. Acreage can grow between
  formal reports but cannot fall below the retained confirmation through a stale edit.
- Observation times, winning source metadata, and sparse field presence survive the
  reconciliation fold. Its complete output is chronological, with no caller ordering
  premise. Later omissions do not erase a previously known value in the latest view.
- A populated independent incident history takes precedence over geography-derived
  fallback reports. Replacing or removing polygon evidence cannot erase that history.

## Source and value provenance

Python deliberately retains an edit's metadata when it substitutes a prior confirmed
value for a stale measurement. The output represents the effective state at the edit's
observation time; it does not claim that the edit originally measured the substituted
value. The formal ledger retains the supporting confirmed observation, and the proofs
establish field-specific value support separately from the selected edit's metadata.
There is no new per-field provenance column or claim that the output row alone
identifies that earlier report. The complete history provides that evidence.

A later **confirmed** report can correct a value even when its report date is older.
Confirmation here is a source-supplied classification, not a proof of source truth or a
monotonically increasing report clock. This matches `incidents.reconcile_updates`.

## Implementation connection

`test_incident_histories.py` compares actual `incidents.reconcile_updates` results with
`oracleIncident`, including every field's effective value, observation clock, source
priority, filename, serial, report clock, and confirmation. It exercises all 1,000
length-three histories over ten report shapes, the empty history, and 300 deterministic
longer histories with five independently sparse fields. Cases include zero values,
conflicting and matching simultaneous reports, out-of-order inputs, dated and undated
confirmations, stale downward edits, interim growth, and newer corrections. It checks
chronology, repeat reconciliation, and latest-value projection as well.

Twenty longer histories additionally traverse raw source attributes,
`fires.incident_history.incident_layer_rows`, a real GeoPackage write/read, normalized
`incidents.history`, and polygon removal/replacement. These compare with the same Lean
reference, including metadata after serialization. Temporary files contain no network or
production data. The source grouping in these cases is one unambiguous fire; identity
composition is checked separately in the presentation inventory.

The oracle accepts `history ENTRY ...`, with each entry encoded as eight comma-separated
integers: observation seconds, direct-feed Boolean, serial, file identity, report
seconds (or `-1`), confirmation Boolean, field identity, and value. It returns the
selected entries in time/field order. Conformance canonicalizes simultaneous row
packaging only; no field metadata is discarded. Integer projections reject fractional
drift, and separate assertions validate each complete source kind and path against its
supporting input. Filenames use fixed-width numeric basenames so their lexicographic
priority agrees with numeric oracle identities. Exact ties preserve input order.

## Boundaries

The theorems quantify over all finite histories; they do not prove Python's
implementation or GeoPackage libraries. The oracle uses nonnegative integer measurements
and discrete UTC seconds. The conformance vectors exercise real numeric normalization
and storage, but fractional rounding, timezone parsing, invalid source values, arbitrary
filesystem faults, and external report truth remain outside these proofs. Normalization
and storage are checked through execution, not a verified serializer. Model results do
not establish that this incident policy is appropriate for every real-world reporting
practice.

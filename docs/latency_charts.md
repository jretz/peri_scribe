# Latency Charts

The latency chart helps answer two questions: how long do pipeline runs take, and how
long after a source publishes a perimeter does a run that writes a KMZ finish? Each
curve shows the fraction of measurements at or below a given duration. That makes both
typical delays and occasional long ones visible.

Run either command in a compatible terminal to show both curves on one chart:

```shell
peri_scribe show-latencies
peri_scribe show-latencies data/2026 --start=-3d --end=-1h
```

## Measurements and retained evidence

- **All pipeline runs:** completed `run` invocations starting and ending inside the
  inclusive window, including publication-gate stops and failures. Duration comes from
  the command's elapsed timer. Incomplete runs have no end time and are excluded.
- **Source publication to end of KMZ-producing run:** one sample per fire receiving new
  source polygon records or polygon timestamp updates available to a run that wrote a
  KMZ. Identical polygon coordinates still qualify. Point updates and incident-only
  attribute changes, such as costs, do not qualify. The endpoint is the command's
  completion, including all phases. A later phase failure still has a sample when the
  run already wrote its KMZ.

The source layer's `lastEdit` timestamp, saved in snapshot filenames, supplies an
estimate of publication time. This measures a different part of the delay from the
perimeter's survey time or the time the pipeline downloaded it. If a run introduces
several versions for one fire, the sample starts at the earliest new source
publication. Source times must also fall inside the window.

The second series reads retained FIRIS and WFIGS polygon snapshots directly. Each
version is identified by its feed, record ID, and polygon timestamps (`poly_DateCurrent`
and `poly_CreateDate`, when present). First appearances count even when the shape matches
another record. Repeated appearances of the same version do not count. When polygon
timestamps are absent, only the record's first appearance can be distinguished from
incident-only edits. Missing or empty polygons are excluded.

The current `sources/fires.json` index supplies canonical fire identities. An earlier
record without identifiers inherits its indexed identity when its source path and name
match one fire unambiguously. Distinct indexed fires keep separate identities even when
they share a name and lack source identifiers. Ambiguous path/name matches fall back to
individual source records. Newly collected records absent from the index retain their own
source identifiers or names. Derived geography, shape reconciliation, size filtering, and
cleaning are not needed. The measurement ends at the completion of a run that had those
source polygons available and wrote a KMZ. It does not establish that each polygon
passed publication filtering or that the KMZ reached an external server.

Diagnostic snapshot-completion records establish which new inputs were available when
geography started. Older snapshots establish which polygon versions already existed.
Recent snapshots without collection evidence in the selected logs are excluded. Retain the
complete logs and source history for the periods being compared. Missing months are
not fabricated; a window with no completed runs returns an error. A window without
new perimeter publications shows an empty second series with unavailable statistics.

## Read-only log access

The command reads the selected year's `logs/YYYY-MM.jsonl` files and, when the window
reaches earlier months, `logs/YYYY-MM.jsonl.zst`. It reads archived records before any
later plain records for the same month. A committed rotation receipt identifies a plain
copy already included in the archive, so that copy is not counted again. The shared
log-rotation lock keeps these components stable during each monthly read. The command
excludes the separate fire-update log series.

Plain files are binary-searched by root timestamp using string tokenization. Archived
files are decompressed incrementally and their old prefixes are skimmed for timestamps
before JSON deserialization begins. A string filter excludes unrelated events before
timestamp extraction and JSON decoding. No archive is expanded to disk or collected
into a single memory buffer. The upper time bound is checked for each record; an event
beyond it does not end the read. An unfinished last line is ignored. Seeking to the
window start assumes dated records are in timestamp order. When a completed run crosses
the window start, its elapsed duration identifies an earlier seek point so its collection,
geography, and KMZ phases remain available for consumption tracking.

The chart uses existing evidence, so the pipeline does no additional work to support
it. The command reads identifying attributes, polygon timestamps, and flags indicating
whether geometry is present directly from the authoritative GeoPackages through
read-only SQLite connections. It does not decode or compare polygon coordinates,
acquire the pipeline lock, or write application logs, caches, or source files.

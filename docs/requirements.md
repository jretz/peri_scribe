# Requirements

## Project: PeriScribe

PeriScribe gathers fire geography from configured ArcGIS feeds, preserves source
snapshots, derives cleaned fire histories, calculates fire scores, and produces a
symbolized KMZ for Google Earth. The current implementation stores data below
`data/<year>/` in the working directory.

## Implemented behavior

The configured fire feeds are:

- CAL FIRE/NIFC perimeters, which retain historical updates.
- WFIGS current perimeters, which retain the latest perimeter for active fires.
- WFIGS current incident locations, which provide fire points.

The pipeline also retrieves California evacuation zones and a nationwide building
centroid database. Fire-feed snapshots are append-only GeoPackages. The evacuation layer
is kept as its latest GeoPackage, while the buildings source is stored as a compact
SQLite database at `sources/buildings.sqlite`. A successful empty evacuation response
clears the stored zones and counts as a change when zones were previously present.
Repeated empty responses leave that empty snapshot unchanged. Retrieval failures retain
the stored version when one exists. Other external ArcGIS sources, including major
cities, treat empty responses as retrieval failures and warn when retaining cached data.

`run` performs the following operations:

1. Fetch fire feeds incrementally, the external sources (buildings, evacuations, and
   major cities), and the administrative-boundary GeoPackage at
   `sources/CA_border_with_AZ_NV_and_OR.gpkg`, which is downloaded only when missing or
   unusable.
2. Write `derived/history_of_full_geography.gpkg` with `perimeter_history`,
   `point_history`, and `incident_history` layers.
3. Write `derived/history_of_differential_geography.gpkg` containing growth rings.
4. Write `derived/fire_scores.json` and `derived/fire_scores_ccdf.html`.
5. Write `maps/PeriScribe Fires <year>.kmz`.
6. Write `reports/PeriScribe Fires <year>.md`.

These operations form the stages fetch, geography, score, kmz, and reports. After fetch,
the later stages run when fire data or evacuation data changed, a full fetch requires a
derived rebuild, unfinished work remains, or `--unconditional` is provided. A single
stage or a range can be selected with `--only`, `--from`, and `--to`. A failed step
stops the pipeline and leaves required work pending for a later invocation.

After successful KMZ generation, `logs/YYYY-MM-fire-updates.jsonl` records each
interesting fire with a new mapped perimeter since the last successful KMZ. Interesting
fires are the distinct fires in any report section before Fire Details. Each JSON line
contains the timestamp, identifier, stable log identity, name, the report's location
text, and measured area in acres as a numeric value with units. Identifier enrichment
and later name changes preserve a fire's acreage history, including normalized spelling
changes when the identifier first arrives. Unrelated fires reusing a historical name
retain separate acreage histories. Mapping corrections linked by retained source
provenance preserve the previous acreage even when the original perimeter is replaced.
Fires without mapped perimeters are omitted.
Changes to incident reports or rankings alone do not produce entries. The first
generation without a saved baseline logs all interesting mapped fires. All log series
rotate at the local month boundary. Closed months remain uncompressed for seven days,
then compress to `.jsonl.zst` on the next write to that series. Fire-update logs also
compress eligible months after successful generation with no new fire updates.

Immediately after logging, the KMZ stage writes `maps/updates.html` and
`maps/updates.json`. The HTML is a static viewer shared by all runs. The JSON contains
the generation time and all nonzero acreage changes from the preceding 48 hours,
including each update's previous mapped acreage from retained logs and compressed
archives. Missing logs across month boundaries are treated as absent history. Missing
previous acreage means an initial change equal to current acreage.
Repeated updates for the same fire remain separate; decreases are included.

The viewer fetches the neighboring JSON immediately on load over HTTP or HTTPS. Every
30 seconds, it checks for changes with HEAD and fetches a changed snapshot without
reloading the page. Only matching strong ETags allow indefinite reuse; weak ETags or
modification time and size are rechecked by downloading at least every five minutes.
Failed or invalid refreshes preserve the displayed snapshot for later retry.
It groups updates into 0–60 minutes, 60 minutes–4 hours, 4–12 hours, 12–24 hours, and
24–48 hours.
The browser clock updates first-hour minute labels, moves entries between groups, removes
expired entries, and controls the fading highlight for updates less than 15 minutes old.
Group counts show distinct fires, with independently toggled time/name sorting. A
case-insensitive name filter preserves that sorting. Each entry shows its name, location,
update time, previous acreage, change, and current acreage. Locations independently
shorten to state abbreviations and then disappear when space is insufficient. All
acreage headings and values align right. The page uses neutral colors except for deltas
and recent-update highlights, and shows only its generation time below the groups.
Additions, moves, and removals animate while respecting reduced-motion preferences.
Each time group can be collapsed independently. Moving updates animate to or from the
closed header when only one of the source and destination groups is collapsed. Moves
between two collapsed groups skip animation. Refreshes preserve the name filter and
each group's sorting and collapsed state.

When loading or refreshing a snapshot introduces an update that would be highlighted in
an expanded group and matches the name filter, a green circle pulses in the favicon for
30 seconds. Each pulse lasts five seconds and fades out completely; the final pulse
leaves no favicon. This notification runs in foreground and background tabs. Its images
are generated in memory without favicon files. Another qualifying update restarts the
30-second notification. Expanding groups and changing the filter do not start one.

Geography reuses complete results for unchanged fires. Reuse requires matching source
observations, geometry, attributes, ordering, provenance, fire identity and membership,
and derivation dependencies. A change rebuilds the affected fire's complete history,
including earlier rings. Missing, incompatible, damaged, or incompletely published reuse
data causes recomputation. Source snapshots remain authoritative and unchanged.

Cleaned area, exterior perimeter length, ring area, and displayed added area are
computed in geography and stored for downstream consumers. Displayed added area must
match the consumer's exact ordered ring sequence. Missing measurements or a different
sequence require calculation for the actual geometry. Scores and presentation remain
freshly generated, including effects of external inputs and time.

The KMZ includes active and inactive fire folders, latest perimeters, progression rings,
fire information, and score-based top fire views.

Current area in scores, charts, balloons, and reports follows one shared policy. Recent
mapping supplies measured geometry area, including downward corrections. Without usable
mapping, incident reports supply area. Reports can replace stagnant mapping when later
growth meets the freshness and corroboration thresholds. The area basis identifies the
supporting observation and its date, even when a policy deadline makes it effective
later. Growth remains a geometry measurement, so it can lag reported current size.

KMZ and report inclusion require a selected historical area of at least 25 acres. A
later downward correction does not remove a fire that qualified earlier. Fires without a
usable dated estimate can qualify from undated geometry or supplied incident, discovery,
or final acreage. Fresh mapping takes precedence over conflicting reports.

Incident history preserves reported size, costs, personnel, and containment
independently of polygon dates and reconciliation. Simultaneous feed conflicts prefer
direct incident fields. Each measurement retains its supporting source and formal-report
confirmation; confirmation for a different value cannot be transferred to it. Chart
legends include only rendered line styles, with stable colors and distinct
mapped/reported area strokes.

## Configuration and operation

Run `peri_scribe --help` for the available commands:

- `run` runs the end-to-end pipeline; `--list-stages` prints each stage and its
  description without running anything.
- `validate-sources` compares incremental snapshots with complete fresh downloads.
- `show-colormap` previews or writes the colormap used for progression rings.

The `run` command accepts an optional year-directory argument; when omitted it defaults
to `data/<current year>`.

- `--full-fetch-interval` fetches fire feeds in full on the first invocation and
  whenever the last successful full fetch is at least six hours old. A full fetch
  refreshes the fire index and requires an unconditional derived rebuild, even when no
  new snapshot is written. Without an interval, fire-feed fetching is incremental.
- `--unconditional` rebuilds the selected stages regardless of input changes and
  bypasses reuse of prior full and differential histories when geography is selected. It
  respects stage selection and retains the download policy for static sources.
- Pending rebuild requirements in `run_state.json` are tracked separately from full
  fetch completion in `sources/fetch_state.json`. Successful fetches cannot clear
  unfinished derived work. Partial selections leave outstanding requirements pending,
  and a later stage cannot clear an unfinished prerequisite.
- Replacement history files and their checksum metadata must permit recovery after an
  interrupted write. Invalid recovery state requires a full derived rebuild.
- Only one `run` invocation may write to a year directory at a time. An overlapping
  invocation logs a skip and exits successfully; failed processes release their lock.

## Future work

Notifications, configurable recipients and delivery rules remain future requirements.

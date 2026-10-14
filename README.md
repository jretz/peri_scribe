# PeriScribe

PeriScribe gathers fire geography from across the United States and turns it into maps
and reports. The goal is to make it easier to understand how fires are changing and
which ones deserve a closer look. How large is a fire? How quickly has it grown? Are
there buildings nearby or evacuation zones overlapping it?

The source data takes some work to make useful. Observations arrive at different times,
perimeters get corrected, and a reported acreage estimate can differ from the area
that's actually been mapped. PeriScribe keeps the original observations, builds cleaned
histories from them, and uses those histories to score fires and produce maps for Google
Earth. Keeping the originals means later corrections can be taken into account.

The [glossary](docs/glossary.md) explains the project concepts and terminology.

## Looking at the maps

The pipeline writes `data/<year>/maps/PeriScribe Fires <year>.kmz`. Open that file in
Google Earth to explore the year's fires.

You can browse active and inactive fires, or look at top fires ordered by name or
score. To follow what's changing, there are views for new and notable fires and for the
fastest growth in acres or percentage. Growth in acres shows how much land was added;
percentage makes it easier to compare fires of different sizes.

There are also views for fires with the most personnel and for active fires the sources
identify as [Type 1 incidents][incident-complexity], the highest incident-complexity
category. Views only appear when they have matching fires. “Top Fires by Name” is
selected initially when it's available.

Expand a fire to see its location and up to three recent perimeter outlines. The
“Interior” folder contains growth rings colored by observation time, so you can see how
the mapped footprint changed over time. The fire's “Progression” tour plays that growth
from oldest to newest. You can also select an individual ring to see how much area it
added.

Click a placemark or perimeter for the fire's area, how that area was determined,
containment, personnel, costs, source, and other reported facts. Where there's enough
history, charts show changes in area, perimeter, containment, costs, and personnel. The
area charts distinguish mapped measurements from reported estimates. That distinction
matters when a fire has grown since its last mapping.

What you can see depends on what the sources provide. The KMZ includes source links and
attribution so you can follow the information back to where it came from.

## How it works

The pipeline uses fire feeds, evacuation zones, building footprints, place locations
from Natural Earth, and state boundaries. The place locations let it describe where a
fire is relative to a named place. A full run has five stages:

1. **Fetch:** Collect new and changed fire observations, refresh the external sources,
   and fetch state polygons to compute the boundary data file (a GeoPackage) when needed.
   Keep the original observations and geographic reference data.
2. **Geography:** Match records to fires, reconcile corrections, and build histories of
   perimeters, points, incident reports, and growth rings.
3. **Score:** Rank fires using size, growth, first mapping, nearby buildings, evacuation
   overlap, and incident complexity. Save the scores along with explanations and a
   distribution chart.
4. **KMZ:** Build the Google Earth maps and record mapping updates for the browser
   viewer, which shows the last 48 hours of updates.
5. **Reports:** Write Markdown reports for selected fires, including their locations,
   current area, and recent growth.

Scores, maps, and reports use the same derived facts. When source observations change,
the pipeline rebuilds the affected fires' histories and reuses histories that haven't
changed. If fire, evacuation, and city data are unchanged and no rebuild is pending, a
routine run ends after fetching. If a stage fails, the unfinished work stays pending so
a later run can retry it.

## Running it

Run `peri_scribe run` for the full pipeline: fetch → geography → score → kmz → reports.
Commands with an optional year-directory argument use `data/<current year>` when you
don't provide one. Run `peri_scribe --help` for command help.

There are a few options for controlling how much work a run does:

- `--only STAGE`, `--from STAGE`, and `--to STAGE` select one stage or a range.
  `--list-stages` lists the stages with descriptions.
- `--unconditional` rebuilds the selected stages even if nothing has changed. If
  geography is selected, it also bypasses reuse of existing histories.
- `--full-fetch-interval` catches source edits that incremental fetching can miss by
  periodically fetching all fire feeds in full. For example, `--full-fetch-interval 12h`
  does a full fetch on the first invocation and on later runs when the last full fetch
  is at least 12 hours old. Each full fetch forces a complete derived rebuild, even if
  it finds no new data.
- `--publish-threshold AREA TIME_DELTA` lets runs collect updates without rebuilding
  outputs for every small change. For example, `--publish-threshold "25 acre" 5m` can
  defer a build until a fire's mapped area has increased or decreased by at least 25
  acres since its last published mapping, or unpublished inputs remain at least five
  minutes after the last completed local KMZ. These checks happen when the pipeline
  runs. Evacuation or place-location changes, scheduled full fetches, unfinished builds,
  and `--unconditional` bypass the wait.

The other commands help with understanding the data and the pipeline:

- `monitor` opens an interactive terminal view of live logs, pipeline phases, run
  history, and the current report. It reads the selected year's existing data while
  the pipeline continues running.
- `show-latencies` charts how long pipeline runs take and estimates the delay from
  sources publishing perimeter updates to the completion of runs that produce a KMZ.
  Each curve shows the fraction of measurements at or below a given duration, so you
  can see both typical delays and occasional long ones. The chart appears inline in a
  compatible image-capable terminal and defaults to the last week. For example,
  `peri_scribe show-latencies data/2026 --start=-3d --end=-1h` selects a shorter window.
  The [latency chart documentation](docs/latency_charts.md) explains the inputs and how
  the measurements are made.
- `show-colormap` previews the progression-ring colormap in a compatible terminal.
- `validate-sources` compares incremental feed snapshots with complete fresh downloads.
  If it finds problems, it leaves the validation data available for inspection.

For more detail, the [architecture and dataflow](docs/architecture.md) explain the
files, network sources, reuse, and recovery behavior. The
[development tools guide](docs/development_tools.md) covers the development setup.

[incident-complexity]: https://training.fema.gov/emiweb/is/icsresource/assets/incident%20complexity%20and%20type.pdf

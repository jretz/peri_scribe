---
name: regenerate-dataflow
description: >-
  Update the pipeline SVGs in README.md and docs/architecture.md, plus documented
  network resources, from PeriScribe's current implementation. Use for maintaining
  pipeline diagrams as the project evolves.
---

# Regenerate the pipeline dataflow diagram

Update [docs/dataflow.svg](../../docs/dataflow.svg) and the Network resources section
in [architecture](../../docs/architecture.md) in place. Regeneration means reconciling
these documents with the implementation, not running the application or rebuilding
its datasets. Keep the static SVG in `docs/`.

Read [architecture](../../docs/architecture.md) and the current SVG first. Treat source
code as authoritative when documentation and implementation disagree. Preserve the
established presentation below unless the user's current request changes it.

## README overview

[docs/pipeline.svg](../../docs/pipeline.svg) is the introductory diagram embedded in
[README.md](../../README.md). Keep it focused on the five stages and their main saved
outputs, including incident-report histories and the browser update viewer. Match the
detailed SVG's palette, type sizes, static format, and light/dark behavior. Downward
arrows show stage order; side arrows connect stages to their outputs. Explain the work
in plain language, leaving file inventories, memory structures, and recovery mechanics
to the detailed diagram. The exhaustive coverage guidance below applies to
`docs/dataflow.svg`. When pipeline behavior changes, keep both diagrams consistent
without expanding the README to the detailed diagram's scope.

## Trace the current pipeline

Start with these source areas, following callers and consumers as needed. These are
entry points, not a frozen inventory; use `rg` to locate renamed or new modules.

- `src/peri_scribe/main.py`, `pipeline.py`, `pipeline_stages.py`, and `paths.py`:
  stage order, selected-stage execution, data roots, and output locations.
- `src/peri_scribe/sources/` and `src/arcgis_access/`: feed configuration, network
  requests, snapshots, record caches, external datasets, and building archives.
- `src/peri_scribe/fires/`, `perimeters/`, `areas.py`, and `incidents.py`: identity
  grouping, reconciliation, geography histories, area selection, and scoring.
- `src/peri_scribe/presentation/`, `kml/`, and `report/`: shared preparation, map
  assembly, and report selection. Follow storage and geometry work into
  `src/spatial_data/` and serialization into `src/kml_io/` when relevant.
- `src/peri_scribe/execution.py`, `preparation.py`, `publication.py`, and
  `pipeline_state.py`: derived working sets, cache reuse, publication gates, and
  retry state.
- `src/peri_scribe/fire_updates.py`, `updates.py`, `logging.py`, `monitor/`, and
  `updates.html`: update publication, recovery journals, logs, observer state, and
  computed browser state.

Inspect filename patterns and representative files under `data/2026`, then reconcile
them with read/write paths in the code. Cover every **class** of file, including
reference data, caches, locks, signatures, checkpoints, recovery files, compressed
logs, backups, and final products. Include supported classes that may be absent in a
healthy run, such as a pending recovery journal. Do not enumerate individual snapshots,
fires, months, or exact instance counts. Extensions alone do not define a file class.

Show significant computed memory structures: identity graphs, derived geometry,
spatial indexes, metrics, selections, summaries, assembly state, and observer state.
Omit objects that merely hold a complete or partial copy of a disk dataset. A derived
structure may still matter when it has a disposable cache on disk.

For each changed class or structure, establish its producer and consumers before
drawing its connections. Distinguish data dependencies from stage order and retry
control. Do not imply that reports consume KMZ bytes simply because reports run later.
The project covers the United States; California-specific inputs do not narrow that
scope.

## Preserve the diagram's presentation

- Keep one static pipeline diagram without tabs, named views, hyperlinks, scripts,
  or other interactive elements. Do not add large page titles or introductory/footer
  prose. Retain the accessible SVG title and description.
- Use an 840-pixel-wide canvas and a view box of the same width. Keep 16-pixel body
  text, 17.6-pixel box headings, and the current annotation styles. Reflow text and add
  vertical space when content changes; do not shrink the text or scale a wider layout
  to fit. Update box heights, connectors, view bounds, and the SVG height
  together. Keep text inside its box with padding.
- Preserve the vertical stage layout, with derived memory and file products beneath
  each stage, followed by shared inputs, control, and recovery. Repeated file classes
  appear once; use relative paths and placeholders for variable names.
- Keep blue for files, green for computed memory, gold for stages, and purple for
  network resources. Preserve CSS color variables and `prefers-color-scheme` so text,
  backgrounds, borders, and arrows follow the host's light/dark mode.
- Keep detailed network resource content in the Network resources section of
  `docs/architecture.md`, with ArcGIS source layers and building index/archive-family
  subsections. Keep only the source-input summary in the SVG. Add newly introduced
  data sources as needed. SDK bootstrap, output-consumer network resources, and
  attribution-link inventories are outside this section's scope.
- Make external resource names clickable Markdown links instead of displaying raw
  URLs. Group state/DC building downloads as an archive family linked through their
  download index, retaining the URL pattern in a Markdown comment. Derive endpoints
  and request behavior from current configuration/code.

## Keep updates easy to review

Edit the existing XML directly. Retain semantic IDs, shared styles, deterministic
element order, and one element per line where practical. Keep unchanged coordinates
when possible, moving following content only when reflow requires it. Avoid SVG
optimizers, minification, editor metadata, random IDs, generated timestamps, text
converted to paths, rasterized labels, and catalogs of individual files. Do not depend
on temporary generators from prior work sessions.

Preserve the inline SVG image and textual Network resources section in
[architecture](../../docs/architecture.md).
Documentation work does not require fetching live feeds, downloading building archives,
or modifying `data/2026`.

## Validate the result

- Parse the SVG with `.venv/bin/python` and `xml.etree.ElementTree`. Check unique IDs,
  marker references, matching canvas/view-box width, and absence of interactive
  elements. Confirm that changed file classes and dependencies are represented
  accurately, and that resource names and links in the Markdown match the code.
- Open the static SVG in a browser at a laptop-sized viewport. Check text wrapping,
  box padding, arrow endpoints, and the bottom edge of the diagram. Check light and dark
  appearance when changing styles; temporary HTML embedding the SVG in containers with
  `color-scheme: light` and `color-scheme: dark` can exercise both themes. Remove any
  temporary preview files and restore temporary viewport overrides when finished.
- If browser tooling is unavailable, render the SVG with an installed renderer and
  inspect the result. Report any unverified theme behavior.
- Run `git diff --check` and the project's Markdown lint for changed Markdown files.
  An SVG/documentation-only update does not require rebuilding the data pipeline.

Return a link to `docs/dataflow.svg` and briefly describe the substantive diagram
changes and validation performed.

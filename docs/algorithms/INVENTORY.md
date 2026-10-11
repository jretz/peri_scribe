# Algorithm coverage inventory

This inventory covers the production Python modules and packaged browser viewer, plus
algorithms in the verification infrastructure. Each module points to the notes for the
complete behaviors it owns or adapts. A link does not assign every helper the note's
highest score. Local adapters can remain straightforward while participating in a
complex protocol; the protocol's explanation still owns their ordering and assumptions.

For straightforward entries, scores are **H/R/M/S/F**: history, rule interaction,
mathematics, scale/representation, and failure/concurrency. Every nonzero contribution
is explained in its row. Zero-only entries declare data, errors, or exports. Docstrings
supply these local contracts. The [rubric](../algorithm_design.md) determines the tier;
[the note index](README.md) groups the human walkthroughs by subject.

## Production modules

### `aircraft_registration`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/aircraft_registration/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [formats.py](../../src/aircraft_registration/formats.py) | [aircraft recognition](aircraft-recognition.md) |
| [parsing.py](../../src/aircraft_registration/parsing.py) | [aircraft recognition](aircraft-recognition.md) |

### `arcgis_access`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/arcgis_access/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [data.py](../../src/arcgis_access/data.py) | [source validation](source-validation.md); [source collection](source-collection.md) |
| [exceptions.py](../../src/arcgis_access/exceptions.py) | **0/0/0/0/0**: exception vocabulary; no decision algorithm. |
| [metadata.py](../../src/arcgis_access/metadata.py) | [source collection](source-collection.md) |
| [retry.py](../../src/arcgis_access/retry.py) | [source collection](source-collection.md) |
| [spatial_reference.py](../../src/arcgis_access/spatial_reference.py) | [source validation](source-validation.md) |

### `document_text`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/document_text/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [encoding.py](../../src/document_text/encoding.py) | [output serialization](output-serialization.md) |

### `kml_io`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/kml_io/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [fragments.py](../../src/kml_io/fragments.py) | [output serialization](output-serialization.md) |
| [geometry.py](../../src/kml_io/geometry.py) | [output serialization](output-serialization.md) |
| [kmz.py](../../src/kml_io/kmz.py) | [output serialization](output-serialization.md) |
| [styles.py](../../src/kml_io/styles.py) | Straightforward **0/1/1/1/0** (3). Color-byte formatting and independent style serialization; fixed-size style values. |
| [tour.py](../../src/kml_io/tour.py) | [progression presentation](progression-presentation.md) |

### `measurement_units`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/measurement_units/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [registry.py](../../src/measurement_units/registry.py) | Straightforward **0/0/0/0/0** (0). Shared unit registry and currency declaration; no algorithm. |

### `peri_scribe`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [areas.py](../../src/peri_scribe/areas.py) | [incident area selection](incident-area-selection.md) |
| [cli_options.py](../../src/peri_scribe/cli_options.py) | Straightforward **0/1/0/0/0** (1). Explicit path wins; otherwise select the current year. |
| [concurrency.py](../../src/peri_scribe/concurrency.py) | [worker lifetimes](worker-lifetimes.md) |
| [exceptions.py](../../src/peri_scribe/exceptions.py) | **0/0/0/0/0**: exception vocabulary; no decision algorithm. |
| [execution.py](../../src/peri_scribe/execution.py) | [geography generations](geography-generations.md) |
| [fire_update_records.py](../../src/peri_scribe/fire_update_records.py) | [update journal](update-journal.md) |
| [fire_updates.py](../../src/peri_scribe/fire_updates.py) | [history ownership](history-ownership.md); [update journal](update-journal.md) |
| [incidents.py](../../src/peri_scribe/incidents.py) | [incident area selection](incident-area-selection.md) |
| [log_reading.py](../../src/peri_scribe/log_reading.py) | [log retention](log-retention.md) |
| [logging.py](../../src/peri_scribe/logging.py) | [log retention](log-retention.md); [update journal](update-journal.md); [monitor evidence](monitor-evidence.md) |
| [main.py](../../src/peri_scribe/main.py) | [pipeline publication](pipeline-publication.md); [output serialization](output-serialization.md) |
| [models.py](../../src/peri_scribe/models.py) | Straightforward **0/1/1/1/0** (3). Local schema checks, normalization, and deterministic identifier preference/sorting; histories are owned by the grouping note. |
| [output.py](../../src/peri_scribe/output.py) | [output serialization](output-serialization.md); [pipeline publication](pipeline-publication.md) |
| [paths.py](../../src/peri_scribe/paths.py) | Straightforward **0/1/0/0/0** (1). Path composition and a year-name validation rule. |
| [phases.py](../../src/peri_scribe/phases.py) | [monitor evidence](monitor-evidence.md) |
| [pipeline.py](../../src/peri_scribe/pipeline.py) | [pipeline publication](pipeline-publication.md) |
| [pipeline_stages.py](../../src/peri_scribe/pipeline_stages.py) | Straightforward **0/0/0/0/0** (0). Enum vocabulary only; no decision algorithm. |
| [pipeline_state.py](../../src/peri_scribe/pipeline_state.py) | [pipeline publication](pipeline-publication.md); [geography generations](geography-generations.md) |
| [preparation.py](../../src/peri_scribe/preparation.py) | [product caching](product-caching.md) |
| [previews.py](../../src/peri_scribe/previews.py) | [preview orientation](preview-orientation.md) |
| [publication.py](../../src/peri_scribe/publication.py) | [pipeline publication](pipeline-publication.md) |
| [terminal_images.py](../../src/peri_scribe/terminal_images.py) | [terminal rendering](terminal-rendering.md) |
| [updates.py](../../src/peri_scribe/updates.py) | [update viewer](update-viewer.md) |

### `peri_scribe/fires`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/fires/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [buffering.py](../../src/peri_scribe/fires/buffering.py) | [fire scoring](fire-scoring.md) |
| [classification.py](../../src/peri_scribe/fires/classification.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [complexes.py](../../src/peri_scribe/fires/complexes.py) | [fire grouping and ownership](fire-grouping-and-ownership.md) |
| [components.py](../../src/peri_scribe/fires/components.py) | [fire grouping and ownership](fire-grouping-and-ownership.md) |
| [derived_layers.py](../../src/peri_scribe/fires/derived_layers.py) | [geography generations](geography-generations.md) |
| [differential.py](../../src/peri_scribe/fires/differential.py) | [corrected growth rings](corrected-growth-rings.md); [geography generations](geography-generations.md) |
| [files.py](../../src/peri_scribe/fires/files.py) | [geography generations](geography-generations.md) |
| [generation.py](../../src/peri_scribe/fires/generation.py) | [geography generations](geography-generations.md) |
| [grouping.py](../../src/peri_scribe/fires/grouping.py) | [fire grouping and ownership](fire-grouping-and-ownership.md) |
| [history.py](../../src/peri_scribe/fires/history.py) | [perimeter reconciliation](perimeter-reconciliation.md); [perimeter geometry policy](perimeter-geometry-policy.md) |
| [identity.py](../../src/peri_scribe/fires/identity.py) | [fire grouping and ownership](fire-grouping-and-ownership.md) |
| [incident_history.py](../../src/peri_scribe/fires/incident_history.py) | [incident area selection](incident-area-selection.md) |
| [index.py](../../src/peri_scribe/fires/index.py) | [geography generations](geography-generations.md) |
| [reuse.py](../../src/peri_scribe/fires/reuse.py) | [geography generations](geography-generations.md) |
| [score_files.py](../../src/peri_scribe/fires/score_files.py) | Straightforward **0/1/0/1/1** (3). Typed score-file validation and one read; ordinary in-memory rows. |
| [scores.py](../../src/peri_scribe/fires/scores.py) | [fire scoring](fire-scoring.md) |
| [scoring.py](../../src/peri_scribe/fires/scoring.py) | [fire scoring](fire-scoring.md) |
| [sources.py](../../src/peri_scribe/fires/sources.py) | [fire grouping and ownership](fire-grouping-and-ownership.md); [geography generations](geography-generations.md) |
| [spatial_products.py](../../src/peri_scribe/fires/spatial_products.py) | [fire scoring](fire-scoring.md); [geography generations](geography-generations.md) |

### `peri_scribe/geo`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/geo/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [data.py](../../src/peri_scribe/geo/data.py) | [source validation](source-validation.md) |
| [database.py](../../src/peri_scribe/geo/database.py) | [parsed source cache](parsed-source-cache.md) |
| [measurements.py](../../src/peri_scribe/geo/measurements.py) | [source validation](source-validation.md) |
| [package.py](../../src/peri_scribe/geo/package.py) | [parsed source cache](parsed-source-cache.md) |
| [parsing.py](../../src/peri_scribe/geo/parsing.py) | [source validation](source-validation.md); [aircraft recognition](aircraft-recognition.md); [fire grouping and ownership](fire-grouping-and-ownership.md) |
| [reading.py](../../src/peri_scribe/geo/reading.py) | [parsed source cache](parsed-source-cache.md) |

### `peri_scribe/kml`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/kml/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [builder.py](../../src/peri_scribe/kml/builder.py) | [output serialization](output-serialization.md) |
| [colormap.py](../../src/peri_scribe/kml/colormap.py) | [progression presentation](progression-presentation.md) |
| [descriptions.py](../../src/peri_scribe/kml/descriptions.py) | [output serialization](output-serialization.md) |
| [fire_data.py](../../src/peri_scribe/kml/fire_data.py) | [presentation selection](presentation-selection.md) |
| [folders.py](../../src/peri_scribe/kml/folders.py) | [output serialization](output-serialization.md); [corrected growth rings](corrected-growth-rings.md) |
| [icons.py](../../src/peri_scribe/kml/icons.py) | [progression presentation](progression-presentation.md) |
| [plot_data.py](../../src/peri_scribe/kml/plot_data.py) | [chart layout](chart-layout.md) |
| [plot_rendering.py](../../src/peri_scribe/kml/plot_rendering.py) | [chart layout](chart-layout.md); [product caching](product-caching.md) |
| [styles.py](../../src/peri_scribe/kml/styles.py) | Straightforward **0/1/1/1/0** (3). Independent draw-order arithmetic and style declarations over bounded outlines. |
| [tour.py](../../src/peri_scribe/kml/tour.py) | [progression presentation](progression-presentation.md) |

### `peri_scribe/monitor`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/monitor/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [app.py](../../src/peri_scribe/monitor/app.py) | [monitor presentation](monitor-presentation.md) |
| [changes.py](../../src/peri_scribe/monitor/changes.py) | [monitor evidence](monitor-evidence.md) |
| [cli.py](../../src/peri_scribe/monitor/cli.py) | Straightforward **0/1/0/0/1** (2). Independent command selection and one application-run boundary. |
| [controller.py](../../src/peri_scribe/monitor/controller.py) | [monitor presentation](monitor-presentation.md) |
| [display.py](../../src/peri_scribe/monitor/display.py) | [monitor presentation](monitor-presentation.md) |
| [events.py](../../src/peri_scribe/monitor/events.py) | [monitor evidence](monitor-evidence.md) |
| [health_presentation.py](../../src/peri_scribe/monitor/health_presentation.py) | [monitor presentation](monitor-presentation.md); [monitor evidence](monitor-evidence.md) |
| [history.py](../../src/peri_scribe/monitor/history.py) | [monitor evidence](monitor-evidence.md) |
| [model.py](../../src/peri_scribe/monitor/model.py) | [monitor evidence](monitor-evidence.md) |
| [presentation.py](../../src/peri_scribe/monitor/presentation.py) | Straightforward **0/1/1/1/0** (3). Independent display rules, ordinary unit formatting and bounded row/text materialization. |
| [projection.py](../../src/peri_scribe/monitor/projection.py) | [monitor evidence](monitor-evidence.md) |
| [rendering.py](../../src/peri_scribe/monitor/rendering.py) | [monitor presentation](monitor-presentation.md) |
| [screenshots.py](../../src/peri_scribe/monitor/screenshots.py) | Straightforward **1/1/0/1/1** (4). One capture sequence, timestamp naming rule, bounded screen rows and exclusive file creation. |
| [session.py](../../src/peri_scribe/monitor/session.py) | [observable monitor sessions](monitor-sessions.md) |
| [sharing.py](../../src/peri_scribe/monitor/sharing.py) | [monitor evidence](monitor-evidence.md) |
| [status.py](../../src/peri_scribe/monitor/status.py) | [monitor evidence](monitor-evidence.md) |
| [status_widgets.py](../../src/peri_scribe/monitor/status_widgets.py) | Straightforward **1/1/0/1/0** (3). Widget focus/refresh state, independent metric rendering and ordinary displayed rows. |
| [storage.py](../../src/peri_scribe/monitor/storage.py) | [monitor evidence](monitor-evidence.md); [log retention](log-retention.md) |
| [striping.py](../../src/peri_scribe/monitor/striping.py) | [terminal rendering](terminal-rendering.md) |
| [tasks.py](../../src/peri_scribe/monitor/tasks.py) | [worker lifetimes](worker-lifetimes.md) |
| [terminal_contract.py](../../src/peri_scribe/monitor/terminal_contract.py) | **0/0/0/0/0**: structural presentation interfaces; no executable decision policy. |
| [theme.py](../../src/peri_scribe/monitor/theme.py) | Straightforward **0/1/0/0/0** (1). Independent constants map statuses to fixed colors. |
| [widgets.py](../../src/peri_scribe/monitor/widgets.py) | [terminal rendering](terminal-rendering.md) |

### `peri_scribe/perimeters`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/perimeters/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [border_classification.py](../../src/peri_scribe/perimeters/border_classification.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [classification_data.py](../../src/peri_scribe/perimeters/classification_data.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [cleaning.py](../../src/peri_scribe/perimeters/cleaning.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [history.py](../../src/peri_scribe/perimeters/history.py) | [perimeter reconciliation](perimeter-reconciliation.md) |
| [history_attributes.py](../../src/peri_scribe/perimeters/history_attributes.py) | Straightforward **0/1/0/1/0** (2). Independent typed fallbacks over one in-memory attribute bag. |
| [identity.py](../../src/peri_scribe/perimeters/identity.py) | Straightforward **0/1/1/1/0** (3). Canonical geometry/time encoding and standard digest over one observation. |
| [progression.py](../../src/peri_scribe/perimeters/progression.py) | [corrected growth rings](corrected-growth-rings.md) |
| [signals.py](../../src/peri_scribe/perimeters/signals.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [size_filtering.py](../../src/peri_scribe/perimeters/size_filtering.py) | [perimeter geometry policy](perimeter-geometry-policy.md) |
| [versions.py](../../src/peri_scribe/perimeters/versions.py) | [perimeter reconciliation](perimeter-reconciliation.md) |

### `peri_scribe/presentation`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/presentation/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [descriptions.py](../../src/peri_scribe/presentation/descriptions.py) | [output serialization](output-serialization.md) |
| [fire_data.py](../../src/peri_scribe/presentation/fire_data.py) | [presentation selection](presentation-selection.md); [incident area selection](incident-area-selection.md) |
| [history_index.py](../../src/peri_scribe/presentation/history_index.py) | [presentation selection](presentation-selection.md) |
| [index.py](../../src/peri_scribe/presentation/index.py) | [presentation selection](presentation-selection.md) |
| [perimeters.py](../../src/peri_scribe/presentation/perimeters.py) | [presentation selection](presentation-selection.md) |
| [prepared_cache.py](../../src/peri_scribe/presentation/prepared_cache.py) | [product caching](product-caching.md) |
| [preview_geometry.py](../../src/peri_scribe/presentation/preview_geometry.py) | [preview orientation](preview-orientation.md) |
| [preview_palette.py](../../src/peri_scribe/presentation/preview_palette.py) | [preview palette](preview-palette.md) |
| [row_values.py](../../src/peri_scribe/presentation/row_values.py) | Straightforward **0/1/1/1/0** (3). Independent typed field fallbacks, JSON decoding, and first-present selection over one row. |
| [score_association.py](../../src/peri_scribe/presentation/score_association.py) | [presentation selection](presentation-selection.md) |
| [selection.py](../../src/peri_scribe/presentation/selection.py) | [presentation selection](presentation-selection.md) |
| [text.py](../../src/peri_scribe/presentation/text.py) | [output serialization](output-serialization.md) |
| [views.py](../../src/peri_scribe/presentation/views.py) | [presentation selection](presentation-selection.md) |

### `peri_scribe/report`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/report/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [gathering.py](../../src/peri_scribe/report/gathering.py) | [presentation selection](presentation-selection.md) |
| [locations.py](../../src/peri_scribe/report/locations.py) | [nearest place](nearest-place.md) |
| [markdown.py](../../src/peri_scribe/report/markdown.py) | [output serialization](output-serialization.md); [presentation selection](presentation-selection.md) |

### `peri_scribe/show_latencies`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/show_latencies/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [cli.py](../../src/peri_scribe/show_latencies/cli.py) | Straightforward **0/1/1/1/1** (4). Single-unit time parsing, base64 transport and one terminal output; evidence, charting and sizing are delegated to their notes. |
| [perimeters.py](../../src/peri_scribe/show_latencies/perimeters.py) | [latency evidence](latency-evidence.md) |
| [runs.py](../../src/peri_scribe/show_latencies/runs.py) | [latency evidence](latency-evidence.md) |
| [sources.py](../../src/peri_scribe/show_latencies/sources.py) | [latency evidence](latency-evidence.md) |

### `peri_scribe/sources`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/peri_scribe/sources/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [administrative_boundaries.py](../../src/peri_scribe/sources/administrative_boundaries.py) | [external source refresh](external-source-refresh.md) |
| [archives.py](../../src/peri_scribe/sources/archives.py) | [external source refresh](external-source-refresh.md) |
| [borders.py](../../src/peri_scribe/sources/borders.py) | [border construction](border-construction.md) |
| [buildings.py](../../src/peri_scribe/sources/buildings.py) | [compact point storage](compact-point-storage.md) |
| [catalog.py](../../src/peri_scribe/sources/catalog.py) | [monitor evidence](monitor-evidence.md) |
| [changes.py](../../src/peri_scribe/sources/changes.py) | [source collection](source-collection.md) |
| [cities.py](../../src/peri_scribe/sources/cities.py) | [external source refresh](external-source-refresh.md); [nearest place](nearest-place.md) |
| [conversion.py](../../src/peri_scribe/sources/conversion.py) | [external source refresh](external-source-refresh.md) |
| [digests.py](../../src/peri_scribe/sources/digests.py) | [source validation](source-validation.md) |
| [downloading.py](../../src/peri_scribe/sources/downloading.py) | [external source refresh](external-source-refresh.md) |
| [external_data.py](../../src/peri_scribe/sources/external_data.py) | [external source refresh](external-source-refresh.md); [source validation](source-validation.md) |
| [external_sources.py](../../src/peri_scribe/sources/external_sources.py) | [external source refresh](external-source-refresh.md) |
| [feed_state.py](../../src/peri_scribe/sources/feed_state.py) | [source collection](source-collection.md) |
| [feed_types.py](../../src/peri_scribe/sources/feed_types.py) | [source collection](source-collection.md) |
| [feeds.py](../../src/peri_scribe/sources/feeds.py) | [source collection](source-collection.md) |
| [fetching.py](../../src/peri_scribe/sources/fetching.py) | [source collection](source-collection.md) |
| [full_fetch_state.py](../../src/peri_scribe/sources/full_fetch_state.py) | [pipeline publication](pipeline-publication.md) |
| [network.py](../../src/peri_scribe/sources/network.py) | [source collection](source-collection.md) |
| [snapshots.py](../../src/peri_scribe/sources/snapshots.py) | [source collection](source-collection.md) |
| [validation.py](../../src/peri_scribe/sources/validation.py) | [source validation](source-validation.md) |

### `spatial_data`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/spatial_data/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [cache_values.py](../../src/spatial_data/cache_values.py) | [product caching](product-caching.md) |
| [centroid_data.py](../../src/spatial_data/centroid_data.py) | [building centroids](building-centroids.md) |
| [centroid_math.py](../../src/spatial_data/centroid_math.py) | [building centroids](building-centroids.md) |
| [centroid_streaming.py](../../src/spatial_data/centroid_streaming.py) | [building centroids](building-centroids.md) |
| [exceptions.py](../../src/spatial_data/exceptions.py) | **0/0/0/0/0**: exception vocabulary; no decision algorithm. |
| [frame_fingerprints.py](../../src/spatial_data/frame_fingerprints.py) | [product caching](product-caching.md) |
| [geometry.py](../../src/spatial_data/geometry.py) | [spatial queries and measurements](spatial-queries-and-measurements.md) |
| [geometry_pool.py](../../src/spatial_data/geometry_pool.py) | [geometry sharing](geometry-sharing.md) |
| [layers.py](../../src/spatial_data/layers.py) | [spatial queries and measurements](spatial-queries-and-measurements.md) |
| [measurements.py](../../src/spatial_data/measurements.py) | [spatial queries and measurements](spatial-queries-and-measurements.md) |
| [overlaps.py](../../src/spatial_data/overlaps.py) | [spatial queries and measurements](spatial-queries-and-measurements.md) |
| [point_store.py](../../src/spatial_data/point_store.py) | [compact point storage](compact-point-storage.md) |
| [product_cache.py](../../src/spatial_data/product_cache.py) | [product caching](product-caching.md) |
| [reference.py](../../src/spatial_data/reference.py) | Straightforward **1/0/0/1/1** (3). Memoized CRS lookup retains ordinary local cache state and delegates one CRS construction. |
| [row_index.py](../../src/spatial_data/row_index.py) | [product caching](product-caching.md) |

### `svg_charts`

| Module | Explanation or local assessment |
| --- | --- |
| [__init__.py](../../src/svg_charts/__init__.py) | **0/0/0/0/0**: package exports or marker; no decision algorithm. |
| [cumulative.py](../../src/svg_charts/cumulative.py) | [chart layout](chart-layout.md) |
| [distribution.py](../../src/svg_charts/distribution.py) | [chart layout](chart-layout.md) |
| [models.py](../../src/svg_charts/models.py) | Straightforward **0/1/0/0/0** (1). Value types and enumerated style properties. |
| [svg.py](../../src/svg_charts/svg.py) | Straightforward **0/1/1/1/0** (3). Standard escaping, bounded font-width lookup and a fixed 1/2/2.5/5/10 tick ladder. |
| [time_series.py](../../src/svg_charts/time_series.py) | [chart layout](chart-layout.md) |

## Browser and verification infrastructure

| Scope | Explanation |
| --- | --- |
| [Packaged viewer](../../src/peri_scribe/updates.html) | [Snapshot and row reconciliation](update-viewer.md), including conditional refresh, layout, aging and notifications. |
| [Formal checker](../../tests/formal/check.py), process/session/corpus helpers | [Verification evidence](verification-tooling.md): admission, cancellation, leases, authenticating checked graphs and staged publication. |
| Formal path matchers, pipeline batching and replay adapters | [Verification evidence](verification-tooling.md): complete paths, hidden choices, shared prefixes, private branch copies and workload balancing. |
| Formal mutation helpers and defect checks | [Verification evidence](verification-tooling.md): exact successful baselines, unchanged test identities and behavioral rejection. |
| [Regular runner](../../tests/helpers/run_test_suite.mjs), coverage collectors/reporters and browser setup | [Verification evidence](verification-tooling.md): fresh invocation/source identity, contributor receipts and combined coverage. Browser installation is a version-selected tool adapter. |
| Domain conformance adapters and reference implementations | The production note for that domain owns the algorithm and links its checks. The [Lean](../../tests/formal/lean/README.md), [TLA+](../../tests/formal/tla/README.md), and [defect](../../tests/formal/defect_checks.md) inventories own model/proof scope and assumptions. |
| Test assertions, factories, fixtures, strategies and doubles | Case construction and observations use the corresponding domain contracts. Shared graph traversal, durable replay and coverage mechanisms belong to the verification note above. Assertions are evidence of the contract, not a separate policy definition. |
| [Mise tasks](../../.mise/tasks), package/tool configuration and [systemd unit](../../systemd/peri-scribe.service) | Straightforward **1/1/0/0/1 = 3** for local task ordering, fixed dispatch and process exit status. Failure coordination inside called tools belongs to their notes. |
| [Migration marker](../../migrations/__init__.py), static resources and skill instructions | No separate runtime algorithm; schemas, constants, source tables and documented workflows supply inputs to the covered behaviors. |

## Keeping coverage current

Update this inventory when adding an owning module or introducing a distinct algorithm.
Reassess the full affected behavior when its assumptions change. Update the linked note,
any accompanying SVGs, the module backlink and the relevant architecture section together.
Keep ordinary test descriptions and formal inventories authoritative for their checks;
document new nontrivial verification machinery in the verification note rather than
classifying it as a fixture merely because it lives under `tests/`.

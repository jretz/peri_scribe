# Algorithm notes

These notes explain why the algorithms make the decisions they do, what they guarantee,
and where those guarantees stop. Each note includes a complexity assessment, worked
examples, resource limits, and links to the implementation and its checks. SVGs help
explain the difficult decisions alongside the text. The [corrected growth
animation](corrected-growth-passes.svg) shows where working copies come from and how
intersection and difference change their geometry. It is the reference example in the
[SVG guidance](../algorithm_design.md#svg-explanations); labeled static states preserve
the intermediate steps without motion. Linear sequences and lists belong directly in
Markdown; figures show relationships that benefit from a visual explanation.

Use the [coverage inventory](INVENTORY.md) to find the note that covers a production
module, or its assessment if the behavior is straightforward. Use [Algorithm
Design](../algorithm_design.md) when adding or changing behavior, and
[Architecture](../architecture.md) for system context. Scores describe how much context
is needed to reason about correctness. Runtime costs and the importance of a policy are
separate questions.

## Animated explanations

These figures show transformations and changing relationships. Each also provides a
labeled explanation without motion, including when reduced motion is requested.

| Animation | What motion explains |
| --- | --- |
| [Corrected growth passes](corrected-growth-passes.svg) | Backward intersections propagate corrections; forward differences retain only new ground. |
| [Courtyard and centroid](assets/centroid-moments.svg) | Changing a courtyard's size and position shifts the centroid of the remaining building. |
| [Perimeter cleaning](perimeter-cleaning.svg) | Detached artifacts disappear and tiny holes fill, while a wholly small fire survives. |
| [Nearest-place measurement](assets/nearest-place-example.svg) | Measuring to the perimeter instead of its centroid changes distances and the winning place. |
| [Preview rotation and fitting](assets/preview-fit.svg) | Rotation changes the uniform scale that fits the same fire into fixed image bounds. |
| [Persistent trie insertion](assets/geometry-trie.svg) | A new parent attaches to the unchanged subtree before the current root switches. |
| [Incident field provenance](incident-provenance.svg) | Winning values travel with their own evidence into separate sparse records. |
| [Coverage interval union](assets/monitor-coverage.svg) | Overlapping intervals merge, while a separate future interval leaves a real gap. |
| [Verification branch copies](assets/verification-prefixes.svg) | Copied state diverges in one continuation while the shared prefix and other copy stay unchanged. |
| [Cumulative observations](assets/chart-cumulative.svg) | A moving cutoff changes the counted set; tied observations enter together. |
| [Pane width clamping](assets/terminal-panes.svg) | The actual divider stops at a limit while the requested position continues moving. |

## Sources and stored representations

| Note | Main reasoning |
| --- | --- |
| [Incremental source collection](source-collection.md) | Candidate completeness, retry decisions and snapshot publication. |
| [Source interpretation and validation](source-validation.md) | Ambiguous coordinate systems, coverage and content identity. |
| [External source refresh](external-source-refresh.md) | Conditional refresh, empty results and staged conversion. |
| [Authenticated parsed source cache](parsed-source-cache.md) | Authenticating receipts, normalized payload dictionaries and ordered rows in one transaction. |
| [Exact compressed cache payloads](compressed-payloads.md) | Reversible byte prediction, bounded zstd frames, canonical identity and transactional dictionaries. |
| [Source-index preparation](source-index-preparation.md) | Joined parallel byte authentication, complete row fingerprints and ordered Merkle manifests. |
| [Source geometry preparation](source-geometry-preparation.md) | Exact compact geometry keys, sharded interning and shared projection evidence. |
| [Reconstructing the interstate border and classification box](border-construction.md) | Snapped adjacency and complete border traversal. |
| [Building footprint centroids from streamed archives](building-centroids.md) | Streaming and numerically stable polygon moments. |
| [Compact point storage and batched containment](compact-point-storage.md) | Quantization, partitioning and exact candidate checks. |
| [Adaptive building-point queries](adaptive-point-queries.md) | Per-tile cost admission, inclusive range search and exact point multiplicity. |
| [Indexed overlaps, streamed layers, and geodesic measurements](spatial-queries-and-measurements.md) | Spatial indexes, ring contributions and coordinate assumptions. |
| [Immutable geometry sharing](geometry-sharing.md) | Persistent trie insertion and collision-safe identity. |
| [Typed product caches and published-row reuse](product-caching.md) | Typed evidence keys, canonical values and transactional row reuse. |
| [Prepared product representations](prepared-product-representations.md) | Exact binary values, streamed fingerprints, guarded payload reuse and shared description rows. |
| [Compact evidence for KMZ generation](kmz-preparation.md) | Qualified histories, projected attributes and shared presentation records. |

## Fire identity, history and policy

| Note | Main reasoning |
| --- | --- |
| [Trailing aircraft registration recognition](aircraft-recognition.md) | Full registrations, suffix boundaries and mission aliases. |
| [Fire grouping and current complex ownership](fire-grouping-and-ownership.md) | Connected components, aliases and complex membership. |
| [Incremental grouping](incremental-grouping.md) | Exact provenance reuse, conservative dependency blocks, deletion-safe partition reuse and exact proximity forests. |
| [Perimeter reconciliation and survey evidence](perimeter-reconciliation.md) | Survey evidence and retrospective revision. |
| [Perimeter geometry: border evidence, rejection, and cleaning](perimeter-geometry-policy.md) | Border evidence, size rejection and cleaning. |
| [Incident evidence and mapped versus reported area](incident-area-selection.md) | Reported versus mapped area on policy timelines. |
| [Corrected history and growth rings](corrected-growth-rings.md) | Backward corrections before forward differencing. |
| [Growth geometry precision and surface area](growth-geometry-and-area.md) | Fixed-grid overlays and consistent straight-edge ellipsoidal area. |
| [Fire score evidence and spatial signals](fire-scoring.md) | Evidence, area tiers and spatial signals. |
| [Fire update history ownership](history-ownership.md) | Transferring durable history to current owners. |

## Execution, publication and observation

| Note | Main reasoning |
| --- | --- |
| [Pipeline scheduling and publication decisions](pipeline-publication.md) | Durable intent, stage prerequisites and publication gates. |
| [Supervised stage processes](stage-processes.md) | Continuous inherited writer leases, exact handoff and joined cancellation. |
| [Authenticated geography generations and reuse](geography-generations.md) | Authenticated full/differential pairs and selective reuse. |
| [Ordered history work and evidence lifetimes](history-work-queues.md) | Completion-driven count and byte admission, ordered outcomes, cancellation and worker settlement. |
| [Bounded source work](bounded-source-work.md) | Pinned compact metadata, exact dependency-block grouping and per-fire source hydration. |
| [Sharing immutable attribute strings](attribute-string-sharing.md) | Bounded exact string reuse with independent mutable containers. |
| [Prepared-product context retention](product-cache-retention.md) | Transactional retirement and physical compaction of obsolete contexts. |
| [Ordered parsed-cache compaction](parsed-cache-compaction.md) | Exact rowid-preserving replacement under stable writer ownership. |
| [Recoverable fire update publication](update-journal.md) | Ordered durable writes, interrupted batches and recovery. |
| [Log rotation, coherent reads, and time windows](log-retention.md) | Rotation receipts, coherent reads and time windows. |
| [Cancellation and monitor resource ownership](worker-lifetimes.md) | Cancellation through admitted work and resource cleanup. |
| [Monitor evidence, coverage, and cached status](monitor-evidence.md) | Planned phases, sparse evidence and incremental cursors. |
| [Observable monitor sessions](monitor-sessions.md) | Domain request ownership, versioned subscriptions, priority and resource retirement. |
| [Monitor presentation scheduling](monitor-presentation.md) | First-frame gating, background preparation, obsolete-result rejection and performance charts for each execution mode. |
| [Latency attribution from retained evidence](latency-evidence.md) | Attributing source publication to the first eligible run. |
| [Verification evidence and execution](verification-tooling.md) | Checked graph paths, prefix replay and fresh coverage evidence. |

## Human-facing output

| Note | Main reasoning |
| --- | --- |
| [Shared fire selection and ranking](presentation-selection.md) | History matching, rank deduplication and growth windows. |
| [Nearest place descriptions](nearest-place.md) | Conditional pruning bound and projected candidate distance. |
| [Fresh boundary fragments within a KML document](fresh-boundary-spill.md) | Bounded compressed temporary storage reuses freshly rendered coordinates during forced publication. |
| [Literal text and streamed output publication](output-serialization.md) | Literal text, cached geometry and streamed publication. |
| [Progression colors, playback, and map icons](progression-presentation.md) | Active-area colors, timed visibility and icon sampling. |
| [Time series and distribution charts](chart-layout.md) | Temporal joins, empirical distributions and knee fitting. |
| [Fire-preview orientation and rendering](preview-orientation.md) | Raster-dependent objective and sampled search limits. |
| [Alpha-aware preview palette reduction](preview-palette.md) | Alpha-aware error and weighted clustering. |
| [Update snapshots and browser reconciliation](update-viewer.md) | Predecessors, conditional refresh and retained DOM occurrences. |
| [Terminal rendering and image sizing](terminal-rendering.md) | Color blending, pane constraints and terminal image sizing. |

# Formal checks

Run `mise formal` from the repository root. The dedicated tasks are independent of `mise
test` and use tool versions recorded in `.mise/mise.lock`.

The pytest phase uses six worker processes with work stealing to balance independent
checks. Override the count with `env PYTEST_ADDOPTS="-n 8" mise formal-conformance`, or
use `-n 0` for serial debugging. Each TLC subprocess can use a 1 GiB heap; choose the
worker count to fit available memory. Nested baseline/mutant checks remain serial.

Pipeline composition distributes every complete history across 48 batches. Identical
complete prefixes execute once, then continuations receive independent copies of their
actual files and complete TLC path. Fresh-replay comparisons and copy-isolation checks
support the explicit assumptions of the Lean prefix-composition proof. Identity feedback,
coordinate-reference selection, and hard-process crash scenarios also expose independent
pytest items. Workers share complete checked model data from this test run through atomic
JSON publication. The next run regenerates its evidence, and no cases or assertions are
omitted for speed.

The TLC matrix runs four configurations concurrently, with isolated state and JVM
temporary directories and complete per-model diagnostics. Conformance TLC processes also
use private JVM temporary directories for extracted standard modules. Use `env
PERI_SCRIBE_TLC_JOBS=1 mise formal-tla` for serial execution. The top-level formal
phases remain sequential.

- [TLA+ models](tla/README.md) check finite protocol safety and conditional liveness.
- [Lean proofs](lean/README.md) establish properties of pure, explicitly scoped models.
- `conformance/` compares real Python and JavaScript behavior with TLC output and the
  Lean executables.
- [Deliberate defect checks](defect_checks.md) require established conformance tests to
  reject isolated production regressions after passing with the unchanged source.
- `mise formal-counterexamples` reproduces documented limits of the current protocols; a
  confirmed counterexample is not a proved guarantee.

The extended checks cover [journal files and builder recovery](tla/journal_replay.md),
[combined pipeline invocations](tla/composition.md),
[perimeter evidence and publication candidates](lean/evidence.md), and
[incremental collection and building database construction](ingestion_extensions.md).
Additional checks cover [raw snapshots and changing remote feeds](tla/snapshots.md),
[parsed snapshot cache transactions](tla/parsed_cache.md),
[complete incident reconciliation and storage](lean/incident_histories.md), and
[identity through presentation and sparse evidence](lean/presentation.md).
Further checks cover [document publication and concurrent feed coordination](tla/collection_publication.md),
[complete perimeter reconciliation and border classification](lean/perimeter_composition.md),
[typed cache encoding](lean/cache_codec.md), and
[building centroids, streaming, and monitor reconstruction](lean/centroids_monitor.md).
Further boundaries include [source-change fingerprints](lean/source_digest.md),
[log rotation and seeking](log_rotation_seeking.md),
[spatial indexes, differential rows, and coordinate conversion](lean/spatial_boundaries.md),
and [geometry sharing and viewer row semantics](lean/geometry_updates.md).

The identity and recovery checks also cover
[anonymous source components](lean/component_identity.md),
[source-validation soundness](lean/source_validation.md),
[ordered timestamp log queries](log_rotation_seeking.md),
[ownership composed with chronological snapshots](lean/projected_snapshots.md),
[ownership recomputation after acknowledgement](lean/identity_recomputation.md), and
[validation of durable update intent](tla/durable_update_validation.md).
Additional composition checks cover [readers during log rotation](reader_rotation.md)
and [complete execution paths and abrupt process termination](execution_assurance.md).
Update-history reading is composed through actual files, rotation receipts, current
ownership, and saved snapshots in [update log chronology](update_log_chronology.md).
The [numerical policy inventory](lean/numerical_policy.md) covers fractional measurements,
binary64 rounding, unit conversion order, and relative publication tolerances.
The [output text inventory](lean/output_text.md) covers literal source text through
Markdown, HTML, XML, and saved KMZ artifacts.
Domain extensions cover [coordinate-reference selection](lean/coordinate_reference.md),
[identity ownership across publications](lean/identity_lifecycle.md), and
[notable selection and chart evidence](lean/policy_details.md).
Further checks cover [raw feed decoding](lean/raw_decoding.md),
[correctable history ownership](lean/identity_transfer.md),
[complete publication baselines](lean/publication_baseline.md), and
[monitor task coordination and shutdown](tla/monitor_tasks.md), and
[observable monitor sessions](tla/monitor_session.md).

See the [formal verification guide](../../docs/formal_verification.md) for commands,
maintenance rules, assumptions, and implementation-conformance requirements.

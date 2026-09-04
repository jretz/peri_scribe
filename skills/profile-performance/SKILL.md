---
name: profile-performance
description: "Measure PeriScribe CPU, memory, I/O, and multiprocessing hotspots on representative local data."
---

# Profile Performance

Use this skill when a PeriScribe workflow is slow, memory-intensive, or sensitive to
process count. Produce measurements and a focused recommendation; do not optimize based
only on inspection.

## Scope and setup

1. Establish the exact command or public function being profiled, the year/data
   directory, expected output, and a reproducible input size. Prefer a local copy or
   fixture data when the workflow writes derived outputs; never profile by downloading
   live feeds unless the user explicitly requests that.
2. Record the environment (`.venv/bin/python`, Python version, platform, and relevant
   dependency versions) and baseline wall time. Use the project's virtual environment,
   not a system interpreter.
3. Choose the lightest suitable measurement:
   - `cProfile` and `pstats` for Python call-time hotspots;
   - `tracemalloc` for Python allocation growth;
   - `/usr/bin/time -l` on macOS for process-level wall time, peak resident memory, and
     I/O;
   - a small controlled comparison of serial and multiprocessing modes for KMZ rendering
     or other worker-based stages.

## Measurement rules

- Profile representative workloads: include enough snapshots, geometries, or building
  tiles to expose scaling behavior, but note the dataset identity and size.
- Separate cold-start effects (imports, Matplotlib font cache) from steady-state
  measurements. Run repeated trials when the result is noisy and report the range or
  median.
- Attribute the cost to a pipeline stage: source reading, geometry operations, building
  queries, scoring, plotting, serialization, or process startup.
- Check correctness after profiling by confirming expected outputs and, when a
  comparison is made, matching output contents or stable digests. Profiling must not
  alter source snapshots.
- Do not add profiling dependencies or change project configuration merely to take
  measurements. If a tool is unavailable, use the standard-library or system tools
  already present and state the limitation.

## Deliverable

Report the command and dataset, environment, baseline, measurements by stage,
peak-memory and I/O observations, and the smallest evidence-backed next step.
Distinguish an observed hotspot from a hypothesis. If recommending a code change,
include the expected tradeoff and a follow-up benchmark; do not implement it unless the
user separately requests an optimization.

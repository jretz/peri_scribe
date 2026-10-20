---
name: profile-performance
description: "Measure PeriScribe CPU, memory, I/O, and concurrency costs on representative local data."
---

# Profile Performance

Use this skill when a PeriScribe workflow is slow, uses too much memory, or changes
performance with worker count. Measure where the time and memory go, then recommend a
focused next step. Code that looks expensive is a reason to measure, not enough evidence
to justify an optimization by itself.

## Scope and setup

Store reports, measurements, scratch scripts, and copied benchmark datasets under
`.cache/profiling/`. The `data/` directory is frequently replaced with production data,
which can erase profiling evidence stored there.

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
   - a controlled comparison of worker counts when the operation allows that choice.

## Measurement rules

- Profile representative workloads: include enough snapshots, geometries, or building
  tiles to expose scaling behavior, but note the dataset identity and size.
- Separate cold-start effects, such as imports and cache population, from steady-state
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

Report the command, dataset, environment, baseline, measurements by stage, peak memory,
and I/O observations. Recommend the smallest next step supported by those measurements,
and distinguish what was measured from what is still a hypothesis. If recommending a
code change, explain the expected tradeoff and how to benchmark it afterward. Implement
it only when the user has also requested an optimization.

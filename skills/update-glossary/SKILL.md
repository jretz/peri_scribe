---
name: update-glossary
description: >-
  Update docs/glossary.md as PeriScribe concepts, terminology, and behavior evolve.
  Use for glossary refreshes or changes that introduce, rename, remove, or materially
  change a documented project concept.
---

# Update the project glossary

Maintain [docs/glossary.md](../../docs/glossary.md) as a concise reference to concepts
used in the current project. Keep definitions grounded in implemented behavior and
preserve the glossary link from [README.md](../../README.md).

## Establish what changed

Read the glossary and relevant parts of [requirements](../../docs/requirements.md) and
[architecture](../../docs/architecture.md). For a focused update, inspect the requested
change and its affected concepts, including staged and unstaged changes when relevant.
For a general refresh, review each glossary section against its owning source modules.
Use `rg` to find renamed modules and new concepts; existing links are starting points,
not a fixed inventory.

Trace definitions to the code that owns the behavior and, where useful, its tests:

- `src/peri_scribe/models.py` and `fires/`: identities, grouping, classification,
  histories, reconciliation, and scoring.
- `src/peri_scribe/sources/`: feeds, snapshots, collection policies, and external data.
- `src/peri_scribe/areas.py`, `incidents.py`, and `perimeters/`: measurement evidence,
  area selection, observation times, and progression rings.
- `src/peri_scribe/presentation/`, `kml/`, and `report/`: qualification, shared facts,
  ranking, and output terminology.
- `src/peri_scribe/pipeline*.py`, `execution.py`, `preparation.py`, and
  `publication.py`: stages, reuse, caches, pending work, and publication.
- `src/peri_scribe/fire_updates.py`, `updates.py`, and `logging.py`: update records,
  stable identities, checkpoints, and the viewer.
- `src/spatial_data/`, `kml_io/`, `svg_charts/`, and `measurement_units/`: spatial,
  format, chart, and unit concepts when the affected definitions need them.

When documentation and code disagree, describe the implemented behavior and identify
the discrepancy. Do not describe a future requirement as an existing capability.
Resolve numerical thresholds, filenames, and policy details from current code instead
of treating values in the glossary or this skill as permanent.

## Revise the definitions

Add concepts that help readers understand project data, behavior, or outputs. Update
changed meanings, merge duplicate explanations, and remove obsolete entries. Keep a
former name as an alias only when it still helps readers interpret current code or data.
Do not turn the glossary into a catalog of every function, class, or dependency.

Keep the topic sections and `- **Term** — Definition` style, placing new terms beside
related concepts. Use short definitions and links to deeper documentation or owning
source files. Keep links relative to the glossary, use backticks for code and paths,
and wrap prose to 88 columns. Update section reference links when ownership moves.

Keep distinctions that affect interpretation explicit: source observations versus
derived histories; mapped, reported, and selected area; observation versus effective
time; ring area versus displayed added area; fire identity versus log identity; and
authoritative data versus disposable caches. Recheck these distinctions when behavior
changes. PeriScribe covers the entire United States even where an input or policy is
specific to California.

Document current concepts rather than change history. Avoid duplicating long policy
tables or procedures that belong in the linked implementation and architecture docs.
Preserve the introduction's convention that data paths are relative to a year directory.
A glossary update should not fetch live sources, rebuild the pipeline, or modify data.

## Validate and report

Check each changed definition against its implementation, including related entries
whose meaning may also have changed. Verify local link targets and Markdown heading
anchors, retain the README link, and check for duplicate terms and stale names.

Run `git diff --check` and the project's Markdown lint on changed Markdown files.
Documentation-only changes do not need the application test suite. If the requested
work also changes code, follow the project's normal testing guidance for that code.

Return a link to the glossary and briefly state the concepts added, changed, or removed
and the validation performed. If it already matches the implementation, report that
without making cosmetic edits merely to produce a diff.

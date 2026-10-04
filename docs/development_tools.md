# Development Tools

## System Requirements

The only tool required on a development system is a recent version of
[`mise-en-place`](https://mise.jdx.dev/installing-mise.html). `mise` is used to manage
isolated, project specific versions of all other tools used for development and testing.

## Python

The project uses Python as provided by [`uv`](https://docs.astral.sh/uv/). `uv` also
manages the virtual environment for the project. `uv` itself is made available by
`mise`. Nothing beyond `mise` needs to be installed on the development system to run
tests, lint, typecheck, create builds, or do deployments. All tools for development and
deployment activities are managed by `mise` and tools it makes available.

## Forgejo CI

The workflow in `.forgejo/workflows/test.yml` runs on pushes and pull requests using
the `ci-base` runner label. It runs `mise test-all`, which runs the standard Python and
viewer tests, coverage checks, linting, type checking, formatting checks, and the formal
suite. The existing setup dependencies install tools with `mise install`, prepare
GEOS, and sync Python dependencies with `uv sync --locked`. Mise uses recorded tool
versions from `.mise/mise.lock`; [strict installation][mise-lock] with
`mise install --locked` additionally rejects missing lock entries and is used when
smoke-testing the runner image.

After all preceding steps succeed on a push to the repository's default branch, the
final step creates or moves the remote `deploy` tag to the commit SHA tested by that
workflow run. It uses the [automatic workflow token][workflow-token] persisted by
checkout; pushes made with that token do not trigger another workflow. Pull requests
and tag pushes do not move `deploy`. Forgejo must allow the workflow token to update
the tag.

The workflow enables Forgejo's failure emails to the user who triggered the run.
Delivery requires [Forgejo server version 12][forgejo-v12] or newer, a configured
mailer, and an enabled email notification preference for that user. The runner version
does not identify the Forgejo server version.

CI sets `PERI_SCRIBE_UV_CACHE_ROOT` to `/tool-cache/uv/peri-scribe`. The mise
configuration appends the GEOS version so Shapely builds for different GEOS libraries
use separate uv caches. Local runs default to `.cache/uv` in the checkout. The GEOS
environment and micromamba root remain checkout-local and are prepared by the existing
setup tasks.

These changes configure existing tool, notification, and Git adapters. The tag update
uses Forgejo's success and event conditions and Git's atomic reference update; there is
no application policy or persistence protocol for an additional formal model to verify.

## Formal verification

Run `mise formal` for the TLA+ model checks, Lean proofs, and implementation conformance
tests. Mise manages Java, TLA+, and Lean with `latest` selectors and records known
versions in `.mise/mise.lock`. Python dependencies are recorded in `uv.lock`.

The formal suite is separate from `mise test`. See [Formal
Verification](formal_verification.md) for individual commands, model inventories,
assumptions, and guidance for maintaining correspondence with the implementation.

## Fire update viewer

Run `mise serve-updates` to serve the current year's `data/<year>/maps` directory using
Python's built-in HTTP server. Open <http://127.0.0.1:8765/updates.html> after
generating the KMZ outputs. The task binds to the loopback interface and needs no
additional server dependency. Stop it with Ctrl-C.

To serve a different year's outputs, pass the directory explicitly:

```sh
mise serve-updates -- --directory data/2025/maps
```

Both local testing and production use HTTP loading because browsers restrict adjacent
JSON requests from pages opened with `file://`. The viewer checks for a new snapshot
every 30 seconds with HEAD and fetches changed data automatically. Changes animate
while preserving the filter, sorting choices, and collapsed groups. Without a strong
ETag, it also downloads at least every five minutes because HTTP modification times
and file sizes can collide. Its age labels, groups, and highlights also update locally
while open.

Run `mise test-viewer` to test the viewer without a browser or network access. The task
requires 100% JavaScript line, branch, and function coverage and runs as part of `mise
run test`. Coverage reports refer to the inline script's lines in `updates.html`.

## Backfill fire update history

Run the standalone migration against a copy of a retained year directory and use a
separate output directory:

```sh
.venv/bin/python -m migrations.backfill_fire_updates \
  /path/to/copied/2026 /tmp/fire-updates-backfill
```

The Click command accepts `--limit N` to replay at most N builds with new perimeters for
a smoke run and `--help` for usage. It reconstructs monthly fire-update logs from
successful KMZ runs and retained history, and writes a checkpoint and an audit under the
output directory.
Closed monthly logs follow the same seven-day compression grace period as normal runs.
An input copy with no successful KMZ builds is rejected without changing the output
directory. Run the migration's isolated regression tests with:

```sh
.venv/bin/python -m pytest -o addopts='' --no-cov -q migrations/test_backfill_fire_updates.py
```

Review the audit before copying the reconstructed logs and checkpoint into the active
year directory. Its `complete` flag indicates whether the output covers every successful
build in the retained evidence. The audit records the requested `limit`, input-history
bounds separately from the covered `first_completed` and `last_completed`, and the
`last_replayed_completed` build that advanced the checkpoint. Unchanged builds count as
covered without consuming the replay limit. An incomplete audit identifies a smoke-run
checkpoint that should not replace the current baseline. The migration does not publish
these files or generate the viewer's `updates.json`; the next successful KMZ phase
generates the viewer files from the logs.

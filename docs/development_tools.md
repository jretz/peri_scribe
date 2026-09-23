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

## Fire update viewer

Run `mise run serve-updates` to serve the current year's `data/<year>/maps` directory
using Python's built-in HTTP server. Open
<http://127.0.0.1:8765/updates.html> after generating the KMZ outputs. The task binds to
the loopback interface and needs no additional server dependency. Stop it with Ctrl-C.

To serve a different year's outputs, pass the directory explicitly:

```sh
mise run serve-updates -- --directory data/2025/maps
```

Both local testing and production use HTTP loading because browsers restrict adjacent
JSON requests from pages opened with `file://`. The viewer checks for a new snapshot
every 10 seconds with HEAD and fetches changed data automatically. Changes animate
while preserving the filter, sorting choices, and collapsed groups. Without a strong
ETag, it also downloads at least every five minutes because HTTP modification times
and file sizes can collide. Its age labels, groups, and highlights also update locally
while open.

Run `mise run test-viewer` to test the viewer without a browser or network access. The
task requires 100% JavaScript line, branch, and function coverage and runs as part of
`mise run test`. Coverage reports refer to the inline script's lines in `updates.html`.

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

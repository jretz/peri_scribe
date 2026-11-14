# Development Tools

## System Requirements

Install a recent version of
[`mise-en-place`](https://mise.jdx.dev/installing-mise.html). It keeps the project's
development tools separate from other installed versions. On Linux, tests that run
Chromium also need its
[system dependencies](https://playwright.dev/docs/browsers#install-system-dependencies).
Install those libraries when preparing the development machine or runner image.

## Python

`mise` installs [`uv`](https://docs.astral.sh/uv/), which supplies Python and manages the
project's virtual environment. Python development and deployment tools run through that
environment. `uv.lock` records the resolved dependencies so the same environment can be
reproduced.

The current lock retains Ruff 0.16.10 because Ruff 0.17's new default aliases conflict
with the project's module-qualified import convention. It also retains pandas 3.0.6:
ArcGIS 2.4.4's spatial accessor imports `infer_dtype_from_object`, a private pandas API
removed in pandas 3.1. The dependency declarations remain open. Recheck the existing
lint rules and actual ArcGIS spatial-dataframe conversions before advancing these
locked selections.

Pytest 9.1.1 is retained because 9.2 does not restore GeoPandas's dynamic options
correctly after `monkeypatch.setattr`, leaving a temporary Fiona engine choice active.
It also changes the existing report-read mock's cleanup behavior. Pint 0.26.1 is
retained because 0.26.2 changes exact acre normalization and invalid-unit failures.
The existing assertions preserve those contracts; their expected values and error
handling remain unchanged.

## Forgejo CI

The workflow in `.forgejo/workflows/test.yml` runs on pushes and pull requests using
the `ci-base` runner label. It runs `mise test-all`, which runs the standard Python and
viewer tests, coverage checks, linting, type checking, formatting checks, and the formal
suite. Setup dependencies install tools with `mise install`, prepare GEOS, sync Python
dependencies with `uv sync --locked`, install JavaScript dependencies with `npm ci`, and
install the Chromium revision required by Playwright. Mise uses recorded tool
versions from `.mise/mise.lock`; [strict installation][mise-lock] with
`mise install --locked` additionally rejects missing lock entries and is used when
smoke-testing the runner image.

The job enables `container.init` so Docker's init process reaps orphaned descendants.
The full test gate waits for owned process groups to disappear before releasing their
capacity. An exited process that has not been reaped can keep its group present and
make that check time out. This setting applies when the runner creates the container;
it works with the runner's keepalive entrypoint and the `ci-base` label's image.
See [Forgejo's container settings][container-init] and [Docker's init process][docker-init].

After all preceding steps succeed on a push to the repository's default branch, the
final step creates or moves the remote `deploy` tag to the commit SHA tested by that
workflow run. It uses the [automatic workflow token][workflow-token] persisted by
checkout; pushes made with that token do not trigger another workflow. Pull requests
and tag pushes do not move `deploy`. Forgejo must allow the workflow token to update
the tag.

Run `mise deploy` to fetch the current `deploy` tag from `origin` and check out its
commit with a detached HEAD. The fetch replaces the local deployment tag when CI has
moved it. Checkout runs only after a successful fetch and uses Git's normal protection
against overwriting uncommitted changes.

The workflow enables Forgejo's failure emails. Push failures notify the user who pushed
the commit; pull-request failures notify the user who opened the pull request. Delivery
requires [Forgejo server version 12][forgejo-v12] or newer, a configured mailer, and an
enabled email notification preference for that user. The runner version does not
identify the Forgejo server version.

CI sets `PERI_SCRIBE_UV_CACHE_ROOT` to `/tool-cache/uv/peri-scribe`. The mise
configuration appends the GEOS version and a hash of its absolute library path. Shapely
builds embed that path, so checkouts in different directories need separate caches even
when they use the same GEOS version. Repeated runs in the same checkout reuse their
cache. Local runs use `.cache/uv` as the cache root. The GEOS environment and micromamba
root remain checkout-local and are prepared by the existing setup tasks.

Shapely 2.2 discovers the native GEOS dependency through pkg-config or CMake. Mise adds
the checkout's GEOS metadata directory to `PKG_CONFIG_PATH`, so its source build uses
the same GEOS 3.15 installation as the runtime library path. The GEOS setup installs
pkg-config alongside the compiler. The older
`GEOS_INCLUDE_PATH`, `GEOS_LIBRARY_PATH`, and `geos-config` discovery methods are no
longer supported by Shapely. See its [custom GEOS build instructions][shapely-build].

[shapely-build]: https://shapely.readthedocs.io/en/2.2.0/installation.html#geos-discovery-compile-time

uv can reuse a cached source build even with `--reinstall-package shapely`; reinstalling
does not guarantee a rebuild. The path-specific cache ensures Shapely is built against
the current checkout's GEOS library. See [uv's cache
documentation](https://docs.astral.sh/uv/concepts/cache/).

The runner's existing bind mount is
`--volume /home/jimmy/forgejo/ci-tool-cache:/tool-cache`. JavaScript setup uses
`npm_config_cache=/tool-cache/npm/peri-scribe` for package downloads and
`PERI_SCRIBE_PLAYWRIGHT_CACHE_ROOT=/tool-cache/playwright/peri-scribe` for browser
binaries. Browser directories include the platform, architecture, and resolved
Playwright version. These are subdirectories of the existing mount; no additional
mounts are required. Browser profiles and test artifacts are private to each test run.

The browser cache saves repeated downloads by retaining executable files. Cookies,
local storage, and application responses stay outside it, so a later run does not
inherit browser session state. Automatic browser garbage collection is disabled because
one job could otherwise remove a revision another job needs. Keep manual cache cleanup
outside active jobs. Playwright's warning about the cost of
[restoring a browser cache][playwright-cache] concerns copied cache archives; this runner
reuses an already-mounted directory.

### Preparing ci-base for browser tests

The runner image is administered separately from this repository. On a Linux release
supported by Playwright, install Chromium's system libraries and fonts while building
`ci-base`. After installing this project's locked JavaScript dependencies, use its
Playwright executable so the dependency list matches the version being tested:

```sh
mise node-dependencies
mise exec -- ./node_modules/.bin/playwright install-deps chromium
```

The second command needs permission to install operating-system packages. Recheck those
requirements when upgrading Playwright. No test task installs system packages.
Headless Chromium needs neither a desktop session nor Xvfb. Keep `/tool-cache` writable
by the runner account, and smoke-test `mise browser-install` followed by `mise
test-browser` from a checkout inside the prepared image. Browser binaries themselves
are supplied through the persistent cache rather than baked into the image.

[playwright-cache]: https://playwright.dev/docs/ci#caching-browsers

The deployment tag depends on Forgejo's success and event conditions and Git's atomic
reference update. The tool and notification configuration uses existing adapters. There
is no additional application policy or persistence protocol here for a formal model to
verify.

[mise-lock]: https://mise.jdx.dev/dev-tools/mise-lock.html
[container-init]: https://forgejo.org/docs/latest/user/actions/reference/#jobsjob_idcontainerinit
[docker-init]: https://docs.docker.com/reference/cli/docker/container/run/#specify-an-init-process
[workflow-token]: https://forgejo.org/docs/latest/user/actions/basic-concepts/#automatic-token
[forgejo-v12]: https://forgejo.org/2025-07-release-v12-0/

## Production systemd units

[`systemd/peri-scribe.service`](../systemd/peri-scribe.service) is a user service that
runs `mise deploy` before each separate invocation of `mise run-production`. The `-`
prefix on `ExecStartPre` allows production to proceed after deployment succeeds or
fails, using whichever commit remains checked out.

[`systemd/peri-scribe.timer`](../systemd/peri-scribe.timer) starts the first cycle one
second after the timer starts and schedules subsequent cycles 60 seconds after the
preceding service activation. A cycle that finishes in less than a minute waits for
the remaining time; a longer cycle is followed immediately by the next one. Timer
accuracy is set to one second. Systemd waits for the service to finish before activating
it again, so cycles do not overlap. The interval covers the whole service cycle,
including deployment, environment setup, the pipeline, and upload. Failed cycles use the
same cadence. Each activation runs its own deployment check.

The unit uses the `/home/jimmy/peri_scribe` checkout and `/usr/local/bin/mise` executable.
It runs as the owner of the user service manager, with no `User` override. The account
needs access to the checkout, Git remote, mise configuration, and the `PeriScribe` rclone
remote used by `run-production`.

`TimeoutStartSec=infinity` disables the startup timeout, so deployment can take as long
as needed. If deployment hangs, production and the next cycle must wait for it to exit.
Sequencing and failure handling use [systemd's service lifecycle][systemd-service], and
the cadence uses [monotonic timers][systemd-timer]. This configuration adds no application
protocol for an additional formal model to verify.

On the production host, validate both units from the checkout as `jimmy` without
starting them:

```sh
systemd-analyze --user verify \
  systemd/peri-scribe.service systemd/peri-scribe.timer
```

Install symlinks to both files, then enable the timer as `jimmy`:

```sh
mkdir -p /home/jimmy/.config/systemd/user
ln -sfn /home/jimmy/peri_scribe/systemd/peri-scribe.service \
  /home/jimmy/.config/systemd/user/peri-scribe.service
ln -sfn /home/jimmy/peri_scribe/systemd/peri-scribe.timer \
  /home/jimmy/.config/systemd/user/peri-scribe.timer
systemctl --user daemon-reload
systemctl --user enable --now peri-scribe.timer
```

The timer's `WantedBy=timers.target` starts it with the user service manager. The service
is activated by the timer and is not enabled directly. To start the user service manager
at boot and keep it running after logout, enable lingering once:

```sh
sudo loginctl enable-linger jimmy
```

When switching an existing installation to the timer, first let deployment pull the
commit containing both unit files. Then run these commands before the installation
commands above:

```sh
systemctl --user daemon-reload
systemctl --user disable --no-reload peri-scribe.service
```

The reload applies the service settings without interrupting a running cycle. Disabling
without `--now` also lets that cycle finish. Disabling may warn that the service has no
installation section; it still removes existing enablement links. It can also remove
the service's symlink to the checkout, which the installation commands restore.
`--no-reload` keeps the manager's configuration intact until both symlinks are in place.

Check the loaded settings and schedule with:

```sh
systemctl --user show peri-scribe.service --property=Restart,FragmentPath,UnitFileState
systemctl --user list-timers --all peri-scribe.timer
```

`Restart=no` confirms that the timer owns repetition. The service can report
`UnitFileState=linked` because it is available to the timer without direct enablement.
While a cycle is running, the timer may have no next expiry displayed; it schedules
the next activation when the service finishes.

Symlinked changes on disk require `systemctl --user daemon-reload` before the manager
uses them. After changing timer settings, also run
`systemctl --user restart peri-scribe.timer`; this leaves an active service running.
To stop future cycles, stop the timer. To stop an active cycle too, stop both units:

```sh
systemctl --user stop peri-scribe.timer peri-scribe.service
```

The unit files are not installed or enabled by any project task.

[systemd-service]: https://github.com/systemd/systemd/blob/main/man/systemd.service.xml
[systemd-timer]: https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml

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

Serve the viewer over HTTP for both local testing and production. Browsers restrict
requests for the neighboring JSON when the page is opened with `file://`.

The viewer checks for a new snapshot every 30 seconds. It sends an `If-None-Match` GET
with the last displayed snapshot's ETag, letting the server return 304 when the data
hasn't changed. A full response updates the display automatically. Changes animate while
preserving the filter, sorting choices, and collapsed groups. ETags are sent unchanged
and do not expire locally; without one, every poll downloads the JSON. Age labels,
groups, and highlights also update locally while the page is open.

Viewer tests use mise-managed Node and project-local JavaScript packages. Keep package
versions in `package-lock.json` and reproduce them with `mise node-dependencies`, which
runs `npm ci`. Run `mise browser-install` to install the matching Chromium build. The
local browser cache root is `.cache/playwright`; set
`PERI_SCRIBE_PLAYWRIGHT_CACHE_ROOT` to relocate it. Installation and execution resolve
the same platform, architecture, and Playwright-version directory. Repeated test runs
reuse the installed browser files. `mise upgrade-dependencies` refreshes npm packages
alongside mise tools and Python dependencies, installs the matching browser, and runs
the regular and formal tests. Review the resulting lockfile changes.

Run `mise test-viewer` for simulated tests and `mise test-browser` for real headless
Chromium tests. Both collect JavaScript coverage without enforcing an individual suite's
percentage. `mise test` includes both suites and finishes with `mise coverage-report`,
which requires 100% combined JavaScript line, branch, and function coverage, alongside
the separate Python coverage requirement. Reports map the script to `updates.html`.
See [Testing](testing.md#browser-viewer-tests) for test ownership, isolated runs, and
browser debugging.

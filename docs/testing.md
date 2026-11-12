# Testing

## Conventions

The project's [coding conventions](conventions.md) also apply to tests and test helpers.

## Decomposition

- Each standard or property-based test module should focus on behavior owned by
  one source module. Multiple test modules may cover that source module, with
  filenames identifying the module or behavior being tested. Tests of a
  coordinating module may exercise interactions across its dependencies.
  Code-analysis tests may inspect multiple modules or the entire codebase.
- Each test should test exactly one thing.
- Where test setup is complicated, factor it into fixtures or reusable helpers.
  Hypothesis tests must isolate state between generated examples. Pytest fixtures are
  not recreated for each example, so use factories or context managers called within the
  test when setup and cleanup must run for every example.
- When a class/method/function is tested by a function, that class/method/function name
  should appear immediately after `test_` in the test function name. For example, if the
  class `MyClass` has a method `my_method`, then a test function for that method should
  be named `test_my_class_my_method`.

## Input/Output

Tests must run without network access. Mock every network interaction, including
ArcGIS FeatureServer requests and requests to other data sources.

Tests must not write application data to the repository or depend on persistent local
application state. Code that intentionally reads or writes files should use pytest’s
per-test `tmp_path` directory or an equivalent isolated temporary location. Hypothesis
tests that modify files must additionally isolate those changes between generated
examples.

Hypothesis’s standard `.hypothesis/` directory is an intentional exception to the
repository-write restriction. Use it for Hypothesis’s example database and other
framework-managed caches so discovered examples can be reused across runs. Tests must
remain runnable when the directory is absent, and must not use it for application data
or test fixtures. Preserve confirmed bugs as explicit regression tests even when
Hypothesis has cached the failing examples.

## Test Coverage

Do not introduce pragmas to ignore test coverage.

## Formal Checks

TLA+ models, Lean proofs, and their implementation-conformance tests live in
`tests/formal/`. They have a separate pytest configuration and are excluded from default
pytest collection and `mise test`. Run them with `mise formal`. Follow [Formal
Verification](formal_verification.md) before implementing new system behavior, when
changing covered behavior, or when adding formal checks. Ordinary regression tests for
discovered implementation bugs remain in the standard test tree.

## Terminal Monitor Tests

Use the monitor session's `show_view` helper before inspecting a tab's rendered rows or
changing its scroll position. After keyboard navigation, filtering, or run selection,
use `settle` when the assertion depends on prepared content. Keep input stable during
these waits. Both monitor fixtures disable automatic file reads and cosmetic timers
and fix the observation clock. A frozen wall clock alone does not stop an asyncio timer
from scheduling another table update. The ordinary fixture opens Pipeline and joins
initial background preparation before yielding. The startup fixture opens Status and
leaves background preparation under test control. Both fixtures join cosmetic-task
cancellation before yielding. Timer and shutdown tests start the real cosmetic loop
explicitly when needed.

Drain queued widget and application messages before joining tab-activation workers and
the controller's display task. The widget queues can send new messages to the app during
the drain. Changing a search field schedules preparation outside Textual's worker
manager, so joining its workers alone leaves that search running. The final refresh lets
table cursor movement and Markdown layout reach the screen before scroll or screenshot
assertions. The scrolling fixture seeds its files before mounting. Its 120-by-32-cell
terminal retains the usual width for edge and stripe assertions, with enough rows in
each pane to exercise its scroll bounds.

The stripe and terminal-edge tests share the seeded scrolling mount across panes in a
theme. Each pane has its own subtest and sets its own scroll positions. The Pipeline
panes run before other tabs, and each other tab opens for the first time from Pipeline.
Headless terminal sessions raise Python's allocation threshold for cyclic collection
to 10,000 when the existing threshold is lower and positive. This reduces collection
work during repeated widget updates. The terminal helper restores the prior thresholds
when the app closes.
Use plain `refresh` for widget changes that do not schedule content preparation. Keep
explicit gates in tests that intentionally inspect work in progress; do not settle
away the concurrency those tests are exercising.

Status-link keyboard actions and exception-row selections post a separate evidence
navigation message. Await the `evidence_completed` fixture, then `settle`, before
checking the selected run, tab, or details. Input delivery can finish while the evidence
reader is still running, and navigation completion can precede queued focus and tab
updates. The fixture observes one navigation. Start selection tests on a different run
so the expected result cannot already be present before navigation.

Keep blocked session requests inside `Gate.running` and register their tasks with
`Gate.start`. The scope releases the gate, joins requests, and closes the session if an
assertion fails. Admitted requests deliberately defer cancellation until their work
finishes, so relying on pytest's task cancellation can leave teardown waiting forever.
Keep the explicit result and cancellation assertions in the test body; cleanup must
preserve the original failure. Replay adapters that create their own owner or session
must also join admitted callers and close that owner on failure, before their
monkeypatches are restored. Cleanup itself must tolerate cancellation while preserving
the original failure. For example, an assertion while three callers are admitted must
release the worker gate, join all three callers, and close their owner even if another
cancellation arrives during that cleanup. The adapters reuse the existing
[worker lifetime contract](algorithms/worker-lifetimes.md); they retain O(C) task
references for C callers and wait for those callers to finish. See the
[session gate helper](../tests/helpers/doubles/peri_scribe/monitor/session.py) and
[replay adapter](../tests/formal/helpers/monitor_tasks.py).

For UI gates, enter `release_on_exit` before dispatching the worker or waiting for
admission. Dispatch can yield before the worker starts, so cleanup must cover both
dispatch and admission waits. The mounted fixture can then finish its pending work during
teardown. See the
[synchronization helpers](../tests/helpers/doubles/peri_scribe/monitor/synchronization.py).

Before asserting that a thread remains blocked during shutdown, observe its attempt
to acquire the actual held lock. A stop signal can acknowledge the shutdown request
before the thread reaches that lock, allowing an unlocked implementation to pass the
assertion under some schedules. Preserve the real lock while observing that boundary;
see the [history helpers](../tests/helpers/doubles/peri_scribe/monitor/history.py).

Keyboard input can finish before the next frame applies pane geometry. Wait for
`refresh` after divider keys before asserting sizes, including assertions that an
ignored key leaves sizes unchanged. `Pilot.press` drains key messages but does not
wait for the resulting frame.

These helpers are thin test adapters over existing completion APIs. Their sequencing
assessment is **2/0/0/0/1 = 3, involved**: control delivery must precede joining work,
and the join must precede paint. They add no application policy or resource protocol
requiring a separate formal model. Event-gated regressions check that a blocked worker
keeps the helper pending and that releasing it produces the expected content. Joining
W active Textual workers uses O(W) temporary space; elapsed time depends on preparation
and rendering. The helpers propagate preparation failures rather than retrying assertions.
See the [monitor fixture](../tests/helpers/fixtures/peri_scribe/monitor/application.py)
and [synchronization regressions](../tests/tests/standard/test_monitor_session.py).

Use `tests.helpers.textual.Session.resize` before checking resized terminal geometry or
scroll bounds. Textual can acknowledge a requested terminal size before its deferred
screen reflow updates child regions. The helper waits for the current screen's outer
size to reach the requested dimensions, then waits for child refreshes. Run resizes
sequentially while keeping the same screen active. The added layout wait has a bounded
timeout, and same-size requests still finish with a refresh barrier.

Mounted sessions use `RefreshPilot` over the same application inside its native
`run_test` lifecycle. Its inherited mouse, keyboard and resize methods still deliver
the actual input events. A default pause drains the native widget queues and waits for
the application's completed refresh. Explicit delays keep Textual's normal behavior;
keyboard dispatch also retains its own native waits. The queue barrier still visits
the mounted widgets, and rendering completes through the real screen. Comparisons
retain every native scenario, inverse drag, assertion and screenshot export.

### Native terminal scenarios

Related native monitor observations share one mount only when they form a coherent
history. Each former case remains a named subtest with its original assertions. Report
checks prepare two replacements before the first Report visit, then exercise links,
paused publication, all four other tab shortcuts, hidden completion and scroll retention.
A separate layout scenario restores divider positions through actual inverse drags and
returns to the default terminal size between viewport probes. The wheel scenario uses
the public Live action and completed Pipeline navigation before each pane; it restores
the inspection fixture's text through the real Static widget update.

Option lists close through actual Escape input before the command palette opens. Each
theme's tint scenario starts with severe events belonging to command `0`, then appends
that command's start and the remaining run outcomes. The same seven run rows therefore
supply the original outcome-color observations. Live-performance checks use one actual
completion for paused collection, the cosmetic clock and the 48-hour expiration. A
separate mount collects all 125 recent completions before adding the five chart groups
used for native resize and scroll checks.

Each scenario still owns an isolated directory, event loop, mounted application and
ordinary fixture teardown. File readers, Textual input, layout, paint and completion
barriers remain native. Screenshot, first-paint, shutdown, cancellation, cleanup and
status-history checks retain independent mounts. Status freshness cases deliberately
control distinct clock histories and should stay separate. Replacing a log file does
not erase the monitor's retained historical evidence and is not a session reset.

This orchestration has assessment **2/0/0/1/1 = 4, involved**: observations depend on their
order, each scenario has bounded in-memory input, and joins coordinate with existing
native completion boundaries. The existing monitor-session and worker models continue
to own application transitions. These test adapters add no application policy, resource
protocol or formal abstraction; native rendering and input checks remain the appropriate
boundary evidence. They retain O(C + W) input/task references for C fixed scenario
records and W active workers, plus the application's ordinary widgets and history.

The qualified monitor cohort contains 609 unchanged cases and 37 original cases now
represented by named subtests inside nine scenario items. Its total is 618 cases and 69
subtests. The original cohort contained 646 cases and 32 subtests. The controlled cohort
comparison preserves all 217 production executed/missing line and branch tables, plus
49 exact assertion syntax trees and seven exact assertion-call trees moved into scenario
helpers. No production source or test fixture changes are required.

### Controller component responsibilities

Controller policy tests use a presentation port over a real `MonitorApp`, domain session,
reader, filesystem and task queue. Each component fixture has its own event loop and year
directory. It joins the same real workers and descriptor cleanup as the mounted fixture.
The recording presentation retains actual immutable health views, prepared event rows,
report observations and generation numbers. Tests control attachment, filters and frame
admission explicitly; expected results still come from their original domain assertions.

Use this fixture for request sharing and priority, obsolete generations, paused snapshot
identity, source/archive ordering, clock policy and cancellation after admission. Keep
worker and application gates in the test body. A component refresh joins controller work;
it does not acknowledge terminal layout or paint. Native evidence navigation and cursor
application reject use through the recording presentation.

Mounted tests own first Status paint, hidden-content preparation, real input routing,
evidence links, table-to-event mappings, Markdown updates, attachment during asynchronous
widget mutation, viewport geometry, cursors, scrolling, dragging, themes and screenshots.
The native presentation delegates the existing widget functions and selectors. Extraction
must pass the unchanged mounted cohort before any assertion moves to the component port.
The [presentation contract](algorithms/monitor-presentation.md) describes this boundary.

Thirty parameter cases across twenty-two functions use the component fixture. Their input
dimensions and assertions remain covered alongside the native witnesses. The controlled
618-case, 69-subtest comparison retains identical executed/missing line and branch tables
for all 218 production files, including the native presentation adapter. This comparison
checks the declared responsibilities; coverage alone does not establish their equivalence.

## Immutable Preparation Environments

Twelve ordinary geography and pipeline test files explicitly request
`reuse_preparation_environment`. Their source code and installed dependencies remain
fixed while their temporary data changes. Each worker retains the actual strings
returned by `preparation.runtime_fingerprint` and `fires.reuse.derivation_context` for
equal inputs. The first request executes the native function. Every later geography
request still reads the boundary's existence and checksum, cache version, and all three
configuration representations. Native runtime fields also remain part of each key.

The fixture keeps complete source bytes and package versions at its first use and
compares them after all worker tests finish. Replaced readers or encoders use the native
functions. The lookup tables belong to that worker; only frozen keys and returned
strings are shared between selected tests. Year directories, product databases, source
data, geometry, and mutable application objects remain independently owned.

Tests that edit source or runtime dependencies use the native functions without this
fixture. In particular, preparation/reuse mutation checks, formal dependency checks,
deliberate-defect workers, and hard-crash workers retain their original execution. The
fixture's fixed-environment assumption excludes temporary source or package edits that
are restored before teardown. Do not request it in a test of those edits. Boundary
changes and configuration changes are supported while it is installed.

Qualification recomputed the original native function at every shared hit. All 422
repeated results matched exactly across the selected 239 cases; 62 preparation and reuse
cases continued to run natively. Four fresh serial runs retained identical production
line and branch sets and test identities. Regression checks cover same-size source edits,
runtime changes, boundary replacement/removal, configuration changes, and replaced
package readers. These observations establish this explicit fixture domain; a matching
source seal alone would not prove arbitrary Python executions equivalent.

This adapter's assessment is **1/1/0/2/1 = 5, involved**. It retains earlier observations,
checks dynamic inputs and replaced bindings, and owns a bounded table for one test
worker. Capturing and verifying S source bytes takes O(S) storage and reading work,
plus package-metadata reads. Each context request still hashes B boundary bytes and
uses an expected O(1) table lookup; D distinct requests retain O(D) keys and strings.
The adapter introduces no application transition or process-lifetime protocol. Exact
native-result comparisons and the boundary regressions check its representation and
isolation obligations without a separate application model.

See the [environment observation adapter] and [opt-in fixtures].

[environment observation adapter]: ../tests/helpers/doubles/peri_scribe/preparation_environment.py
[opt-in fixtures]: ../tests/helpers/fixtures/peri_scribe/preparation.py

## Browser Viewer Tests

The fire update viewer has two complementary JavaScript suites:

- `mise test-viewer` uses Node's built-in test runner with simulated clocks, HTTP
  responses, and browser elements. Keep pure logic, validation, error combinations, and
  precise timing boundaries here when a browser adds no useful fidelity.
- `mise test-browser` uses Playwright Test with actual headless Chromium. Keep checks of
  DOM behavior, text fitting, CSS layout, font loading, resizing, keyboard interaction,
  focus, collapsed groups, and animations here. Tests exercise the shipped HTML and
  inline JavaScript together.

Both tasks are part of `mise test` and can also run independently. Browser tests use one
worker and start with a fresh context unless the test file opts into reuse. The viewer
heading and group tests reuse a tab across cases. Playwright navigates it to an empty
document and resets viewport, media, the clock, and routes before the next case. Each
case still opens the shipped page, drives real browser input and layout, and starts and
stops a fresh V8 recording. The browser runner publishes coverage only after the suite
passes.

The [viewer context reset check] uses two successive cases to exercise those resets,
including focus and JavaScript state. Run the entire file when focusing on the reset.
Use a fresh context for tests that depend on browsing history or `window.name`, change
permissions or context-wide settings such as geolocation and request headers, or alter
browser-wide state. The viewer cases rely only on the state covered by the reset check.

Test requests are fulfilled from fixtures through interception, including the page
itself. Unexpected requests fail the test. No server or external network access is
needed. Use controlled clocks for polling and elapsed-time behavior instead of real
waits.

[viewer context reset check]: ../tests/tests/browser/peri_scribe/test_viewer_context.mjs

Install the locked JavaScript dependencies with `mise node-dependencies`, then install
the matching Chromium build with `mise browser-install`. These setup steps may download
packages or browsers; executing tests is offline. The browser cache contains binaries
only. Do not store test profiles, application data, or reports there. Linux hosts also
need browser system libraries; see [Development Tools](development_tools.md).

### Combined coverage

The test tasks collect native V8 coverage without requiring each suite to cover the
entire script. The final `mise coverage-report` task merges both JavaScript suites and
requires 100% line, branch, and function coverage. Python retains its separate 100%
coverage requirement. `mise test` runs Python tests and linting, then runs the viewer,
browser, type, and formatting checks together before reporting coverage. `mise test-all`
fixes lint issues before opening the formal evidence session. Its default ordinary
Python run assigns whole files to four independent pytest sessions alongside one TLC
check at a time. Each session collects and runs its assigned files with the regular
fixtures. The coverage report uses the merged evidence from the four successful
sessions. Custom pytest invocations use the standard runner. The full gate checks
models one at a time, builds Lean, and executes the isolated pristine targets alongside
ordinary checks. After both the proofs and the complete ordinary and QA process group
exit successfully, one stock pool starts all five formal workers. Every worker collects
the complete formal inventory. The controller preserves native collection and protocol
reports without changing xdist scheduling. Native numerical libraries use one thread
per worker. Other explicit worker configurations retain the sequential formal phases
and the existing model-slot release after ordinary completion.

The full-test environment sets `PYTHON_CPU_COUNT=1`, so Python discovers one CPU when
choosing default worker counts. Explicit parallel tests still select their own worker
counts, including four native buffer workers with out-of-order completion and ordered
geometry results. This setting changes discovered defaults; it does not impose an
operating-system CPU quota or a hard limit on simultaneous threads.

The coverage tools verify that Node and Chromium tested the same production script
and map gaps to its lines in `updates.html`. Coverage includes the complete script,
even code that neither suite executes. Test helpers and HTML/CSS do not count toward
that percentage. Browser assertions still need to check layout and interaction: a line
can execute without producing the right display or response.

Each complete test run collects fresh coverage. Both JavaScript suites must succeed in
that run; missing, empty, stale, or mismatched results fail the combined check. A
standalone suite collects its own coverage without satisfying another run's
requirements. That lets focused browser work proceed without running unrelated tests
or failing because the other suite hasn't run.

Full runs store results in a new `.cache/coverage/javascript/run-<identifier>` directory;
`.cache/coverage/latest-run.json` identifies the latest full run for `mise
coverage-report`. That command reports an existing run; it does not collect missing
contributions. JavaScript reports live under the session's `report/` directory, with
HTML, JSON, and LCOV formats. Python stores `python-data` and `python-coverage.json` in
the same session. Direct Python runs use `.cache/coverage/data`. These paths allow an
existing `.coverage` file to remain in the checkout. Preserve the session directory when
investigating a failure. These generated files are ignored by Git.

### Focused browser work and debugging

Playwright arguments can be passed through the browser task:

```sh
mise test-browser -- --grep 'heading'
mise test-browser -- --headed
mise test-browser -- --trace on
```

Headed mode needs a graphical desktop, or Xvfb on Linux; regular headless runs do not.
Set `DEBUG=pw:browser` when investigating browser launch failures. Screenshots for
failed tests and requested traces are written under the invocation's `browser-results/`
directory. Inspect a trace with the project-local tool:

```sh
mise exec -- ./node_modules/.bin/playwright show-trace /path/to/trace.zip
```

Standalone browser runs use their own session directory and do not replace the latest
full-run pointer. Use `mise test` for the complete combined gate after focused work.

Formal viewer checks run separately and use their own supporting helpers. Browser
execution and coverage collection do not change application policies or the modeled
refresh behavior. Run `mise formal` when changing shared helpers to check that the
implementation still agrees with the formal definitions.

## What to Test For

Test the behavior independently of how the code implements it. Changing a constant,
such as the default number of retries, should not by itself break a test. Replacing a
function's internals with library calls should also leave tests passing when the
behavior stays the same.

When a bug is found because of something other than a standard test, add a regression
test and confirm that it fails without the fix.

## Property Based Testing

Where appropriate, add tests using the Hypothesis library. Tests based on Hypothesis
should not replace standard tests, not even to achieve 100% coverage. When Hypothesis
exposes a bug, preserve a minimized reproducing case in a standard regression test. Some
things that are a good use of property based testing:

- invariants
- idempotency (e.g., repeatable normalization)
- round trips (e.g., encoding+decoding)
- equivalent inputs (e.g., different units)
- commutativity and associativity
- sorting and filtering
- edge-case and boundary discovery
- agreement with an independent reference implementation

Other uses can make sense too. Before adding a Hypothesis test, identify what varying
the inputs will help check.

Properties should express behavioral guarantees independently of the implementation,
with appropriate numerical tolerances where needed.

The shared `correctness` Hypothesis profile in `tests/conftest.py` disables per-example
deadlines so CPU contention and filesystem latency do not fail correctness checks. Keep
example counts bounded where generation or execution is expensive. Generation health
checks remain enabled; reuse expensive strategies across examples without narrowing
their input domains.

Prefer strategies inferred from type annotations when they describe the intended input
domain adequately. Use constrained or custom strategies to express domain restrictions
and relationships between inputs.

## Test Directory Structure

Organize tests and their supporting code as follows:

```text
tests/
  __init__.py
  conftest.py
  helpers/
    fixtures/
    factories/
    strategies/
    doubles/
    assertions/
    reference/
  tests/
    code_analysis/
    standard/
      peri_scribe/
    property_based/
      peri_scribe/
    browser/
      peri_scribe/
```

Keep Python directories importable with `__init__.py` files. Create directories only
when needed. JavaScript browser tests live in `tests/tests/browser/` with reusable
Playwright fixtures under `tests/helpers/browser/`.

### Test Placement

- `code_analysis/` contains checks of the codebase itself, such as import dependency
  checks and the prohibition on tool-disabling comments.
- `standard/` contains tests using explicit examples, including parametrized tests and
  regression cases originally discovered by Hypothesis.
- `property_based/` contains tests that use Hypothesis to generate examples.
- `browser/` contains Playwright tests against the shipped viewer in Chromium.

Within `standard/` and `property_based/`, mirror the package directories under `src/`,
including `peri_scribe/`. Split modules containing both standard and property-based tests
between these trees. Supporting code shared by either tree belongs in `helpers/`.

Files named `test_*.py` or `test_*.mjs` contain actual tests. Place fixtures, helper
functions, supporting classes, and shared test data in `helpers/`.

### Helper Categories

Choose a helper's category according to its primary purpose:

- `fixtures/`: Functions decorated with `@pytest.fixture`, including fixtures that supply
  factories or test doubles.
- `factories/`: Functions that construct concrete test objects or data.
- `strategies/`: Named or custom Hypothesis strategies. Simple uses of built-in strategies
  can remain in test decorators or test bodies.
- `doubles/`: Replacements for dependencies, including stubs, fakes, mocks, call recorders,
  and the functions that configure or construct them.
- `assertions/`: Reusable assertions and comparisons.
- `reference/`: Independent implementations used to calculate expected results.

Other supporting code, such as code-analysis utilities, can occupy descriptive modules
or packages directly under `helpers/`. Introduce additional categories when existing
code demonstrates a distinct purpose.

Keep constants, type aliases, and supporting dataclasses with the helpers they describe.
Split modules that mix independently useful helpers from different categories.

### Helper Ownership and Mirroring

Within each helper category, mirror the relevant source package directories where a
clear owner exists. Helper module names may differ from source module names.

Choose placement by the concept or workflow a helper supports:

- Helpers for a domain object belong with that object's source module, even when tests
  in several subpackages use them.
- Setup for a workflow belongs with the module coordinating that workflow. It can compose
  helpers from several subpackages.
- Helpers covering several domains without a clear owner belong in a descriptively
  named module at the nearest shared package level.
- Helpers independent of application concepts can live directly under their category.

For example, factories for `peri_scribe.models.FireRecord` belong in
`helpers/factories/peri_scribe/models.py`. Fixtures configuring the CLI pipeline belong
in `helpers/fixtures/peri_scribe/main.py`, even when they replace operations in several
subpackages.

Tests and helpers may import helpers from other package branches. Reuse existing helpers
without duplicating them or moving them merely because another package starts using
them. Keep cohesive scenarios together and avoid circular dependencies.

### Fixture Discovery and Global Setup

Keep the root `tests/conftest.py` limited to setup that applies throughout the test tree
and suite-wide pytest configuration. Universal autouse fixtures and their supporting
fixtures may remain there.

Define other fixtures in `helpers/fixtures/`, retaining their `@pytest.fixture`
decorators. Register their modules through an explicit `pytest_plugins` list in the root
`tests/conftest.py`. Update that list when fixture modules are added or moved.

Importing a fixture module alone does not make its fixtures discoverable. Registration
makes fixtures available; ordinary fixtures still execute only when requested directly
or through another fixture.

Keep fixture names unique across registered modules. Tests and helpers must import
shared constants and functions from helper modules rather than from `conftest.py`.

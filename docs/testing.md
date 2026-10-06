# Testing

## Conventions

[Conventions](conventions.md) — Coding conventions and style guide for the project also
apply to testing code.

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

No tests should touch the network in any way. All network access should be mocked out.
This includes ArcGIS FeatureServer and any other data sources.

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
worker and reuse its browser process, with a fresh isolated browser context for every
test. Test requests are fulfilled from fixtures through interception, including the
page itself; unexpected requests fail the test. No server or external network access
is needed. Use controlled clocks for polling and elapsed-time behavior instead of real
waits. Application state remains private to each test.

Install the locked JavaScript dependencies with `mise node-dependencies`, then install
the matching Chromium build with `mise browser-install`. These setup steps may download
packages or browsers; executing tests is offline. The browser cache contains binaries
only. Do not store test profiles, application data, or reports there. Linux hosts also
need browser system libraries; see [Development Tools](development_tools.md).

### Combined coverage

The test tasks collect native V8 coverage without requiring each suite to cover the
entire script. The final `mise coverage-report` task merges both JavaScript suites and
requires 100% line, branch, and function coverage. Python retains its separate 100%
coverage requirement. `mise test` runs Python tests, simulated viewer tests, linting,
type checking, formatting checks, browser tests, and finally the coverage report.
`mise test-all` runs this sequence and then the formal suite.

Coverage identifies the same production script in Node and Chromium, verifies its
source text, and maps reported gaps to the inline script's lines in `updates.html`.
The complete script is in scope, including code that neither suite executes. Test
helpers and HTML/CSS are outside the JavaScript coverage denominator. Browser layout
and interaction assertions provide assurance that a percentage cannot express.

Each complete test invocation owns fresh coverage output. The combined gate requires
successful contributions from both suites in that invocation and rejects missing,
empty, stale, or source-mismatched results. Standalone test runs collect their own
results and do not satisfy a different run's coverage requirements. This lets focused
browser work proceed without unrelated tests or an incomplete-coverage failure.

Full runs store results in a new `.coverage/javascript/run-<identifier>` directory;
`.coverage/latest-run.json` identifies the latest full run for `mise coverage-report`.
That command reports an existing run; it does not collect missing contributions.
JavaScript reports live under the session's `report/` directory, with HTML, JSON, and
LCOV formats. Python stores `python-data` and `python-coverage.json` in the same session.
Preserve the session directory when investigating a failure. These generated files are
ignored by Git.

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

The existing formal viewer checks remain separate and retain the helpers they need.
Adding a browser runner and coverage adapters does not change application policies or
modeled refresh behavior. Run `mise formal` when changing shared helpers to verify the
existing implementation connections.

## What to Test For

Tests should ensure behavior is correct and they should be independent of
implementation. For example, if code constants change (e.g., the default number of
retries), tests should still pass. If a function body has most of its code replaced with
calls to a library, but it behaves in the same way, tests should still pass.

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

Good use cases are not limited to the above, but don't force things into Hypothesis
without identifying the value of doing so.

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

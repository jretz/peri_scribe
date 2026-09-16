# Testing

## Conventions

[Conventions](conventions.md) — Coding conventions and style guide for the project also
apply to testing code.

## Decomposition

- Each test module should test exactly one module of the codebase, and be named for that
  module.
- Each test should test exactly one thing.
- Where test setup is complicated, factor it into fixtures or reusable helpers.
  Hypothesis tests must isolate state between generated examples. Pytest fixtures are
  not recreated for each example, so use factories or context managers called within the
  test when setup and cleanup must run for every example.
- When a class/method/function is tested by a function, that class/method/function name
  should appear immediately after `test_` in the test function name. For example, if the
  class `MyClass` has a method `my_method`, then a test function for that method should
  be named `test_my_class_my_method`.
- `test_*.py` files should only contain actual tests, not helpers or fixtures

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

Prefer strategies inferred from type annotations when they describe the intended input
domain adequately. Use constrained or custom strategies to express domain restrictions
and relationships between inputs.

# Testing

## Conventions

[Conventions](../docs/conventions.md) — Coding conventions and style guide for the project also apply to testing code.

## Decomposition

- Each test module should test exactly one module of the codebase, and be named for that module.
- Each test should test exactly one thing.
- Where test setup is at all complicated, it should be factored out into a fixture.
- When a class/method/function is tested by a function, that class/method/function name should appear immediately after `test_` in the test function name. For example, if the class `MyClass` has a method `my_method`, then a test function for that method should be named `test_my_class_my_method`.

## Input/Output

No tests should touch the network in any way. All network access should be mocked out. This includes access to ArcGIS Hub, and any other data sources.

No tests should write to disk. All file access should be mocked out, or done through in memory files.

## Test Coverage

Do not introduce pragmas to ignore test coverage.

## What to Test

Tests should ensure behavior is correct and they should be independent of implementation.
For example, if code constants change (e.g., the default number of retries), tests should still pass. If a function body has most of its code replaced with calls to a library, but it behaves in the same way, tests should still pass.

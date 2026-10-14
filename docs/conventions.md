# Conventions

The code needs to be easy for people to read and understand. Clear, concise, consistent
code makes it easier to check the reasoning and change it without missing a consequence.

## Overall Style

Prefer small functions at module level. When a class makes sense, prefer a frozen,
keyword-only dataclass. Use enums for values with distinct meanings instead of strings
or integers. Add type hints to every function argument and return value.

Linting and type checking run as part of the test suite. Never change the `ruff` or
`ty` rules in `pyproject.toml`. Avoid disabling rules on individual lines; that is
acceptable only when a third-party library is incompatible with type hints. In that
case, disable only the specific rule, keeping the other checks active. Resolve linting
and type checking errors even when they appear cosmetic.

Do not leave dead code in the codebase.

Code must be wrapped to fit in 88 columns. But do not wrap code that will fit in 88
columns.

## Comments and Docstrings

All classes, functions, and methods should have docstrings. Where applicable, they
should have "Args", "Returns", "Yields", and "Raises" sections. The exception is pure
tests (named test_*, and appearing in test_*.py files). They should not have docstrings,
and their name should make clear exactly what is being tested.

Comments and docstrings should explain why the code makes its choices. The code itself
shows how the work happens. Describe the current behavior and its reasons without
contrasting it with earlier implementations.

All English prose in code, whether in comments or docstrings, should be wrapped to fit
in 88 columns. If the first word on the next line (with any adjacent punctuation) will
fit on the previous line, it must be moved there.

## Algorithm Documentation

Follow [Algorithm Design](algorithm_design.md) to assess reasoning complexity before
implementing new algorithms and when changing existing behavior or assumptions. The
classification determines whether docstrings, a focused explanation, or a dedicated
design note is required. Keep algorithm walkthroughs and derivations in documentation,
with links from owning modules; comments and docstrings continue to explain why.
Algorithm notes should make liberal use of explanatory SVG graphics, with animation
only where it aids understanding, following the guide's SVG requirements. Write simple
linear sequences and lists directly in Markdown rather than drawing them as SVGs.

## Import Style

In general, avoid using `from <module> import <name>`. Instead, use `import <module>`
and qualify the use of things that come from that module. Where there is a well
established convention for renaming something on import (e.g., `import numpy as np` or
`import pandas as pd`), that is acceptable, otherwise stick to original names. Do not
use `import *`. Avoid circular imports.

## Naming Conventions

Abbreviations are not used in this codebase. All variable names, function names, and
constants are written out in full. Exceptions are reserved for universally understood
abbreviations (e.g., KML, ID, URL, args, kwargs) and conventional single-letter loop
variables (`i`, `j` for indices; `a`, `b` for sort comparators). Terms like longitude,
latitude, minimum, and maximum are written out in full, rather than abbreviated to
`lon`, `lat`, `min`, and `max`.

## Real World Units

Use a `pint` quantity whenever a variable, parameter, or return value has real-world
units. This keeps callers from having to assume a particular unit. Everything should
use the shared unit registry. A DataFrame or NumPy array loaded from a source can stay
in its native form, but derived in-memory DataFrames and arrays should use `pint` units
as well.

An exception to the ban on `from <module> import <name>` is the units registry. Use
`from measurement_units import units` everywhere.

## Calling Functions and Methods

When a function or method, whether in this project's source code or in a library, has a
default value for an argument, never pass the default value for that argument (unless it
happens to be the result of a dynamic expression).

## Runtime State

Almost all functions should be pure: they have no side effects and do not depend on
external state. Keep state in frozen dataclasses in almost all cases. To change data,
pass in the existing dataclass and return a new one with the changes applied. Explicit
inputs and outputs make the code easier to reason about and test.

## Persistent State

Keep functions that read or write external data, caches, and outputs as small as
possible. They should do only the read or write. Keeping other decisions outside those
functions makes it easier to mock the I/O in tests and change a source or output format.

## Public vs. Private

Treat functions, methods, variables, and classes as public. Do not use leading
underscores to mark them private. When direct access could cause a problem, require
access through a method or property. That accessor needs to provide a meaningful
boundary; simply returning the underlying object may leave the same problem in place.

## Migration

When behavior changes, do not reference the old behavior in comments or docstrings.
Instead, describe the new behavior.

Where migration code is desirable, make it a standalone script in a folder called
`migrations` in the root of the project. The script should be idempotent and tested on a
copy of the production data. Nothing in `src` or `tests` should reference the migration
code.

## Reuse

Do not copy and paste code, even when the copy would change a few constants or a small
part of the behavior. Extract the shared work and make the differences explicit. After
extracting it, run the existing tests to check that the original caller's behavior is
unchanged before making further test changes.

## Logging

Wherever a log entry is made as a result of an exception, include `exc_info`.

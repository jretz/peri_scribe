# Conventions

The code exists for the purpose of being easily read and understood by humans. This means that the code should be clear, concise, and consistent.

## Overall Style

Prefer small, module level functions for everything. Where classes make sense, frozen, kw-only dataclasses are preferred. Where values have meanings, use enums instead of strings or integers. Type hints should be used for all function arguments and return values.

Use `mise lint` to check style and format code. Use `mise typecheck` to check for type hints. Never make changes to `ruff` or `ty` rules in pyproject.toml. Work hard to avoid disabling them on a given line of code. That is only acceptable where third party libraries are not compatible with type hints. When a rule is disabled on a line, only disable the specific rule, not type checking altogether. Do not dismiss linting or type checking errors, even if you think they are not important (e.g., only cosmetic).

Do not leave dead code in the codebase.

## Comments and Docstrings

All English prose in code, whether in comments or docstrings, should be about "why", not "how". The code is the truth about how. Such prose should be about the current code, and should not contrast the current code with past code.

## Import Style

In general, avoid using `from <module> import <name>`. Instead, use `import <module>` and qualify the use of things that come from that module. Where there is a well established convention for renaming something on import (e.g., `import numpy as np` or `import pandas as pd`), that is acceptable, otherwise stick to original names. Do not use `import *`. Avoid circular imports.

## Naming Conventions

Abbreviations are not used in this codebase. All variable names, function names, and constants are written out in full. Exceptions are reserved for universally understood abbreviations (e.g., KML, ID, URL) and conventional single-letter loop variables (`i`, `j` for indices; `a`, `b` for sort comparators). Terms like longitude, latitude, minimum, and maximum are written out in full, rather than abbreviated to `lon`, `lat`, `min`, and `max`.

## Calling Functions and Methods

When a function or method, whether in this project's source code or in a library, has a default value for an argument, never pass the default value for that argument (unless it happens to be the result of a dynamic expression).

## Runtime State

Almost all functions are pure functions, meaning they do not have side effects and do not depend on any external state. State should almost always be in frozen dataclasses. Modifications to data should involve passing in a frozen dataclass, and returning a new frozen dataclass with the modifications applied. This makes it easier to reason about the code, and makes it easier to test.

## Persistent State

Functions that interact with external data sources and generated state (cached data, output, etc.) should be as small as possible. They should do nothing beyond the actual read or write operation. This makes it easier to create mocks for testing, and makes it easier to change the underlying data source or output format in the future.

## Public vs. Private

Treat all functions, methods, variables, classes, etc. as public. Do not use leading underscores to indicate otherwise. When there is a concern about exposing something publicly, make all access to it go through a method/property/etc. Ensure that accessor does not expose the underlying object so directly that there is no point to have the accessor.

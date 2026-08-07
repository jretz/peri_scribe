# Conventions

## Overall Style

Prefer small, module level functions for everything. Where classes make sense, frozen, kw-only dataclasses are preferred. Where values have meanings, use enums instead of strings or integers. Type hints should be used for all function arguments and return values. Use `mypy` to check type hints.

Use `make lint` to check style and format code. Use `make typecheck` to check for type hints. Never make changes to `ruff` or `ty` rules in pyproject.toml. Work hard to avoid disabling them on a given line of code. That is only acceptable where third party libraries are not compatible with type hints. When a rule is disabled on a line, only disable the specific rule, not type checking altogether.

## Naming Conventions

Abbreviations are not used in this codebase. All variable names, function names, and constants are written out in full. Exceptions are reserved for universally understood abbreviations (e.g., KML, ID, URL) and conventional single-letter loop variables (`i`, `j` for indices; `a`, `b` for sort comparators). Terms like longitude, latitude, minimum, and maximum are written out in full, rather than abbreviated to `lon`, `lat`, `min`, and `max`.

## Runtime State

Almost all functions are pure functions, meaning they do not have side effects and do not depend on any external state. State should almost always be in frozen dataclasses. Modifications to data should involve passing in a frozen dataclass, and returning a new frozen dataclass with the modifications applied. This makes it easier to reason about the code, and makes it easier to test.

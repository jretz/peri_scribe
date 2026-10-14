# AGENTS.md — Project guidance for AI agents

## Project Docs

- [Requirements](docs/requirements.md) — Requirements for the project.
- [Writing Style](docs/writing_style.md) — Read and follow when writing or editing
  project-authored text for people to read, including documentation, comments,
  docstrings, help text, and generated explanations. Apply it where the text has room
  to explain something; short labels need to stay short.

## Implementation Docs

- [Development Tools](docs/development_tools.md) — Tools and setup for development.
- [Conventions](docs/conventions.md) — Coding conventions and style guide for the
  project. These must be read and adhered to when writing code.
- [Algorithm Design](docs/algorithm_design.md) — Complexity assessment and documentation
  requirements. Read before designing or implementing new algorithms. Reassess existing
  algorithms when changing behavior or assumptions, and provide the required explanation.
- [Testing](docs/testing.md) — Testing guidelines and instructions for the
  project. These must be read and adhered to when writing code.
- [Formal Verification](docs/formal_verification.md) — Model, proof, and conformance
  guidelines. Read before designing or implementing new system behavior, and when
  changing formally covered behavior or formal checks. Verify applicable designs before
  writing implementation code.
- [Architecture](docs/architecture.md) — Architecture and design of the project.

## Environment and Tooling

### Tool Versions

Use `latest` version selectors for development tools managed by `mise`. Commit the
resolved versions and checksums in `.mise/mise.lock` to preserve known toolchains.
Upgrade through mise and review the lockfile changes. Do not duplicate those version
pins in task commands or secondary toolchain files.

For Python dependencies managed by `uv`, keep version declarations open unless a
documented compatibility requirement needs a constraint. Commit resolved dependency
versions in `uv.lock`. Use `uv lock --upgrade` to refresh them and `uv sync --locked` to
reproduce the recorded environment. Do not copy lockfile versions into `pyproject.toml`.

### Shell

Determine the shell in use (bash, fish, zsh, etc.) early in a turn that will involve
shell commands so that they can be formatted correctly for that shell from the start.

### Python Virtual Environment

A sandbox may block access to the cache directories used by `mise` and `uv`. Use the
Python interpreter already in `.venv` to run Python commands there, for example,
`.venv/bin/python my_script.py my_args`. The `python` on the project's path also uses
that environment. The `run-tests` skill explains how to run the required checks in a
sandbox.

### Skills

Project skills describe repeatable workflows and ways to work within sandbox limits.
Use them when they fit the task.

- [Regenerate dataflow](skills/regenerate-dataflow/SKILL.md) — Update the pipeline SVG
  from the current implementation while preserving its layout and readable diffs.
- [Update glossary](skills/update-glossary/SKILL.md) — Keep project concept definitions
  aligned with the current implementation and documentation.

## Geographic Area of Interest

PeriScribe covers the entire United States. California appears frequently because it
has rich data sources used by the project; those sources do not limit its geographic
scope.

# AGENTS.md — Project guidance for AI agents

## Project Docs

- [Requirements](docs/requirements.md) — Requirements for the project.

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

`mise` and `uv` can be difficult in a sandbox because their cache directories are not
accessible. To run Python commands in a sandbox, use `python` on the path (which will
get the one in .venv). For example, `.venv/bin/python my_script.py my_args`. There is
also a skill called `run-tests` for running tests in the sandbox.

### Skills

There are a number of skills available for use in this project. They help get around the
limitations of the sandbox and provide a more structured way to perform tasks. Use them
when appropriate.

- [Regenerate dataflow](skills/regenerate-dataflow/SKILL.md) — Update the pipeline SVG
  from the current implementation while preserving its layout and readable diffs.
- [Update glossary](skills/update-glossary/SKILL.md) — Keep project concept definitions
  aligned with the current implementation and documentation.

## Geographic Area of Interest

This project is about the entire United States. It might appear to be about California
because that state has rich data sources that are being used. But the project is about
the entire country.

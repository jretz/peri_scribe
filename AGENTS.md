# AGENTS.md — Project guidance for AI agents

## Project Docs

- [Requirements](docs/requirements.md) — Requirements for the project.

## Implementation Docs

- [Open Questions](docs/open_questions.md) — Open questions and discussions related to the project.
- [Development Tools](docs/development_tools.md) — Tools and setup for development.
- [Conventions](docs/conventions.md) — Coding conventions and style guide for the project.
- [Testing](docs/testing.md) — Testing guidelines and instructions for the project.
- [Architecture](docs/architecture.md) — Architecture and design of the project.

## Environment and Tooling

### Shell

Determine the shell in use (bash, fish, zsh, etc.) early in a turn that will involve shell commands so that they can be formatted correctly for that shell from the start.

### Python Virtual Environment

`mise` and `uv` can be difficult in a sandbox because their cache directories are not accessible. To run Python commands in a sandbox, use the interpreter in the virtual environment directly. For example, `.venv/bin/python my_script.py my_args`.

### Skills

- [create-kmz-in-sandbox](skills/create-kmz-in-sandbox/SKILL.md) — Generate PeriScribe KMZ files from existing local derived data when multiprocessing or sandbox constraints make the normal CLI unreliable.
- [run-tests](skills/run-tests/SKILL.md) — Run project tests in a sandbox (this should be done at the end of every turn that modifies code to ensure the changes do not break existing functionality).

## Off Limits

Do not modify any of the following files. Tell me you need a change and I will make it for you.

- pyproject.toml
- uv.lock
- mise.toml
- mise.lock
- any markdown files (AGENTS.md, README.md, docs/*.md, etc.)

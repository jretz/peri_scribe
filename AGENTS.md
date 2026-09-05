# AGENTS.md — Project guidance for AI agents

## Project Docs

- [Requirements](docs/requirements.md) — Requirements for the project.

## Implementation Docs

- [Development Tools](docs/development_tools.md) — Tools and setup for development.
- [Conventions](docs/conventions.md) — Coding conventions and style guide for the
  project.
- [Testing](docs/testing.md) — Testing guidelines and instructions for the project.
- [Architecture](docs/architecture.md) — Architecture and design of the project.

## Environment and Tooling

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

## Off Limits

Do not modify any of the following files. Tell me when you need a change and I will make
it for you.

- pyproject.toml
- uv.lock
- mise.toml
- mise.lock
- tests/test_no_pragmas.py
- any markdown files (AGENTS.md, README.md, docs/*.md, etc.)

## Geographic Area of Interest

This project is about the entire United States. It might appear to be about California
because that state has rich data sources that are being used. But the project is about
the entire country.

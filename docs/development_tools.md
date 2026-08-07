# Development Tools

## System Requirements

The only tools required on a development system are `make` (default system versions should be fine) and a recent version of [`mise-en-place`](https://mise.jdx.dev/installing-mise.html). `mise` is used to manage isolated, project specific versions of all other tools used for development and testing.

## Python

The project uses Python as provided by [`uv`](https://docs.astral.sh/uv/). `uv` also manages the virtual environment for the project. `uv` itself is made available by `mise`. Nothing beyond `make` and `mise` needs to be installed on the development system to run tests, lint, typecheck, create builds, or do deployments. All tools for development and deployment activities other than `make` are managed by `mise` and tools it makes available.

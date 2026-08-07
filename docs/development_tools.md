# Development Tools

## System Requirements

The only tool required on a development system is a recent version of [`mise-en-place`](https://mise.jdx.dev/installing-mise.html). That is used to manage isolated, project specific versions of all tools used for development.

## Python

The project uses Python as provided by [`uv`](https://docs.astral.sh/uv/). `uv` also manages the virtual environment for the project. `uv` itself is made available by `mise`. Nothing beyond `mise` needs to be installed on the development system to run tests, lint, typecheck, create builds, or do deployments. All tools for development and deployment activities are managed by `mise` and tools it makes available.

---
name: run-tests
description: "Run project tests in a sandbox."
---

# Run Tests in a Sandbox

Use this skill at the end of every turn that modifies code to ensure the changes do not
break existing functionality.

Run the offline KMZ stage directly from the project root with the `python` that's on the
path (that will get the one in .venv):

```bash
pytest;
ruff format --check;
ruff check;
ty check;
rumdl_bin="$(mise which rumdl)" ; "$rumdl_bin" check;
```

All tests should run in well under a minute.

The ruff format check will give a warning about COM812 - ignore that. Do not ignore (or
cause tooling to ignore) any other warnings or errors that arise from any of the test
stages.

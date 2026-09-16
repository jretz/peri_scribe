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
.venv/bin/pytest;
.venv/bin/coverage json --quiet --fail-under=100 -o .coverage/coverage.json;
.venv/bin/ruff format --check --config 'lint.ignore = ["COM812"]';
.venv/bin/ruff check;
.venv/bin/ty check;
rumdl_bin="$(mise which rumdl)" ; "$rumdl_bin" check;
```

All tests should run in well under a minute.

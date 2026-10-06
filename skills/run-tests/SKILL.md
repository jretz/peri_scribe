---
name: run-tests
description: "Run project tests in a sandbox."
---

# Run Tests in a Sandbox

Use this skill at the end of every turn that modifies code to ensure the changes do not
break existing functionality.

Run the regular checks from the project root:

```sh
mise test
```

The task creates a fresh coverage session, runs the Python and simulated viewer tests,
linting, type checking, formatting checks, and real-browser tests, then enforces Python
and combined JavaScript coverage. Do not replace it with separately collected results:
the final gate requires both JavaScript suites from the same invocation. `mise test-all`
also runs the formal suite; use it when the changes require formal verification.

Mise prepares the locked Python and JavaScript dependencies. `mise browser-install`
installs the Chromium build required by the project-local Playwright package. Linux
browser system libraries must already be present. Setup can require downloads; test
execution is offline. Repeated runs reuse package and browser caches.

For focused development checks, use the appropriate individual task:

```sh
mise test-viewer
mise test-browser
mise test-browser -- --grep 'heading'
```

The individual JavaScript tasks record their own coverage without enforcing the
combined threshold. Run the complete `mise test` after focused checks. See
[Testing](../../docs/testing.md#browser-viewer-tests) for reports and browser debugging.

If sandbox restrictions prevent access to mise's existing tools or caches, or prevent
Chromium from launching, use the available execution permission mechanism for the same
check. Do not suppress checks or download alternate tooling to disguise a sandbox
failure. Report any checks that remain blocked.

For a targeted Python test that does not need mise setup, use the existing virtual
environment directly:

```sh
env TEXTUAL_ANIMATIONS=none .venv/bin/pytest --no-cov path/to/test_module.py
```

This focused invocation does not replace the final combined coverage check. Do not
promise a fixed runtime; browser startup and host load affect repeated-run timings.

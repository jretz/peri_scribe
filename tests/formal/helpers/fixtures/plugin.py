"""Register formal fixtures in both the repository and standalone formal suites."""

pytest_plugins = [
    "tests.formal.helpers.fixtures.corpus",
    "tests.formal.helpers.fixtures.defects",
    "tests.formal.helpers.fixtures.pipeline_composition",
    "tests.formal.helpers.fixtures.process_crashes",
]

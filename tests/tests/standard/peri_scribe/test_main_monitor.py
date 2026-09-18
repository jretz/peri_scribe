"""The monitoring CLI resolves standard locations without becoming a data writer."""

import pathlib
import typing
import unittest.mock

import pytest

import peri_scribe.cli_options
import peri_scribe.main
import peri_scribe.monitor.app
import peri_scribe.paths
import tests.helpers.peri_scribe.main


if typing.TYPE_CHECKING:
    import click.testing


@pytest.mark.asyncio
async def test_monitor_starts_without_pipeline_dependencies(
    tmp_path: pathlib.Path,
) -> None:
    imported = await tests.helpers.peri_scribe.main.monitor_imports(tmp_path / "2040")
    forbidden = {
        "peri_scribe.pipeline",
        "peri_scribe.kml.builder",
        "peri_scribe.report.markdown",
        "peri_scribe.sources.external_sources",
        "arcgis",
        "geopandas",
        "pandas",
    }
    assert not imported & forbidden


@pytest.mark.parametrize("explicit", [True, False])
def test_monitor_launches_read_only_observer_with_resolved_paths(
    runner: click.testing.CliRunner,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    *,
    explicit: bool,
) -> None:
    application = unittest.mock.Mock(spec=peri_scribe.monitor.app.MonitorApp)
    constructor = unittest.mock.Mock(return_value=application)
    monkeypatch.setattr(peri_scribe.monitor.app, "MonitorApp", constructor)
    directory = (
        tmp_path / "2040"
        if explicit
        else peri_scribe.cli_options.default_year_directory()
    )
    result = runner.invoke(
        peri_scribe.main.cli,
        ["monitor", str(directory)] if explicit else ["monitor"],
    )
    assert result.exit_code == 0
    assert constructor.call_args.args[:2] == (
        directory,
        peri_scribe.paths.markdown_report_path(directory),
    )
    application.run.assert_called_once_with()
    assert not directory.exists()

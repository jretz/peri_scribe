"""City reference updates must follow the checked HTTP and replacement protocol."""

import pathlib

import pytest

import tests.formal.helpers.conditional_download
import tests.formal.helpers.conditional_download_crashes
import tests.formal.helpers.corpus


@pytest.mark.parametrize("existing", ["absent", "valid"])
@pytest.mark.parametrize("boundary", ["partial", "validated", "published"])
def test_fetch_cities_database_recovers_after_process_death(
    tmp_path: pathlib.Path,
    existing: str,
    boundary: str,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "ConditionalDownload",
        "ConditionalDownload",
        tmp_path / "model",
    )
    tests.formal.helpers.conditional_download_crashes.replay(
        graph,
        tmp_path / "processes",
        existing=existing,
        boundary=boundary,
    )


@pytest.mark.parametrize("existing", ["absent", "invalid", "valid"])
@pytest.mark.parametrize("validators", ["none", "modified", "etag", "both"])
@pytest.mark.parametrize(
    "scenario",
    list(tests.formal.helpers.conditional_download.Scenario),
)
def test_fetch_cities_database_matches_checked_refresh_protocol(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: str,
    validators: str,
    scenario: tests.formal.helpers.conditional_download.Scenario,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "ConditionalDownload",
        "ConditionalDownload",
        tmp_path / "model",
    )
    tests.formal.helpers.conditional_download.replay(
        graph,
        tmp_path / "year",
        monkeypatch,
        existing=existing,
        validators=validators,
        scenario=scenario,
    )


def test_conditional_download_rejects_publish_before_conversion_and_validation(
    tmp_path: pathlib.Path,
) -> None:
    graph = tests.formal.helpers.corpus.graph(
        "ConditionalDownload",
        "ConditionalDownload",
        tmp_path / "model",
    )
    checked = tests.formal.helpers.conditional_download.contract(
        graph,
        previous=True,
        validators="etag",
    )
    path = checked.start(tests.formal.helpers.conditional_download.Projection(final=1))
    requested = tests.formal.helpers.conditional_download.Projection(
        final=1,
        request="etag",
    )
    path = path.transition("Request", requested)
    published = tests.formal.helpers.conditional_download.Projection(
        final=2,
        request="etag",
        staged=2,
        validated=True,
        outcome="fresh",
    )
    assert published in checked.values.values()
    with pytest.raises(AssertionError, match="no compatible TLC event"):
        path.transition("Publish", published)

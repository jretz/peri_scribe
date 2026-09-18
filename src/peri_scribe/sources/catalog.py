"""Configured source names and locations shared by observers and collectors."""

import us

import peri_scribe.exceptions
import peri_scribe.phases
import peri_scribe.sources.archives
import peri_scribe.sources.external_data
import peri_scribe.sources.feeds


BUILDINGS_STATES = tuple(state.name for state in (*us.states.STATES, us.states.DC))


def buildings_state_urls() -> dict[str, str]:
    """Return the state-to-archive-URL mapping from the repo's page.

    The per-state archive links live in the "Download links" table of the repository
    page named by ``BUILDINGS_SOURCE.url``; the page is loaded only when the archives
    are about to be downloaded, so a change in the link scheme is picked up
    automatically.

    Returns:
        The mapping from state name to archive URL.

    Raises:
        ExternalDataError: If the page cannot be downloaded, holds no download links, or
            is missing a link for one of the states.
    """
    html_text = peri_scribe.sources.archives.fetch_page_text(BUILDINGS_SOURCE.url)
    links = peri_scribe.sources.archives.download_links(html_text)
    if not links:
        message = f"No download links found on {BUILDINGS_SOURCE.url}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    missing = [state for state in BUILDINGS_STATES if state not in links]
    if missing:
        message = f"No download link for {', '.join(missing)} on {BUILDINGS_SOURCE.url}"
        raise peri_scribe.exceptions.ExternalDataError(message)
    return links


BUILDINGS_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="buildings",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.DOWNLOAD,
    url="https://github.com/microsoft/USBuildingFootprints",
    states=BUILDINGS_STATES,
    state_urls=buildings_state_urls,
    compact_database=True,
)


EVACUATIONS_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="evacuations",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.ARCGIS,
    url=(
        "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/"
        "CA_EVACUATIONS_CalOESHosted_view/FeatureServer/0"
    ),
    layer_name="evacuations",
)


MAJOR_CITIES_SOURCE = peri_scribe.sources.external_data.ExternalSource(
    name="major_cities",
    kind=peri_scribe.sources.external_data.ExternalSourceKind.ARCGIS,
    url=(
        "https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/"
        "USA_Major_Cities_/FeatureServer/0"
    ),
    layer_name="major_cities",
)


EXTERNAL_SOURCES = (BUILDINGS_SOURCE, EVACUATIONS_SOURCE, MAJOR_CITIES_SOURCE)


def configured_phase_branches() -> peri_scribe.phases.Branches:
    """Give execution and observers the same configured source instance names.

    Returns:
        Feed and external-source branches used to expand the phase catalogue.
    """
    return peri_scribe.phases.Branches(
        feeds=tuple(feed.name for feed in peri_scribe.sources.feeds.FEEDS),
        sources=tuple(source.name for source in EXTERNAL_SOURCES),
        evacuations=EVACUATIONS_SOURCE.name,
    )

"""Status controls preserve presentation and emit only actionable evidence targets."""

import pytest
import rich.text
import textual.events
import textual.widgets

import peri_scribe.monitor.status
import peri_scribe.monitor.status_widgets
import peri_scribe.monitor.theme
import tests.helpers.factories.peri_scribe.monitor.status
import tests.helpers.fixtures.peri_scribe.monitor.status_widgets
import tests.helpers.textual


def test_status_pane_show_view_uses_health_colors_and_symbols(
    status_session: tests.helpers.fixtures.peri_scribe.monitor.status_widgets.Session,
) -> None:
    session = status_session
    text = session.app.query_one("#status-overview", textual.widgets.Static).content
    assert isinstance(text, rich.text.Text)
    assert peri_scribe.monitor.theme.RED in str(text.style)
    assert "✗" in text.plain


@pytest.mark.asyncio
async def test_status_pane_ignores_observations_without_navigation_targets(
    status_session: tests.helpers.fixtures.peri_scribe.monitor.status_widgets.Session,
) -> None:
    session = status_session
    link = session.app.query_one(
        "#status-failure",
        peri_scribe.monitor.status_widgets.StatusLink,
    )
    await tests.helpers.textual.invoke(link.on_click)
    await tests.helpers.textual.invoke(link.on_key, textual.events.Key("x", "x"))
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
    await tests.helpers.textual.invoke(
        pane.select_evidence,
        textual.widgets.DataTable.RowSelected(table, 0, next(iter(table.rows))),
    )
    await session.refresh()
    assert session.app.opened == []


@pytest.mark.asyncio
async def test_status_pane_show_exceptions_preserves_selection_as_count_changes(
    status_session: tests.helpers.fixtures.peri_scribe.monitor.status_widgets.Session,
) -> None:
    session = status_session
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    first = tests.helpers.factories.peri_scribe.monitor.status.failed_run(
        run_id="first",
    )
    await tests.helpers.textual.invoke(
        pane.show_view,
        tests.helpers.factories.peri_scribe.monitor.status.view(*first),
    )
    table = pane.query_one("#status-exceptions", textual.widgets.DataTable)
    selected = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
    await tests.helpers.textual.invoke(
        pane.show_view,
        tests.helpers.factories.peri_scribe.monitor.status.view(
            *first,
            *tests.helpers.factories.peri_scribe.monitor.status.failed_run(
                run_id="latest",
            ),
        ),
    )
    assert table.coordinate_to_cell_key(table.cursor_coordinate).row_key == selected
    assert table.get_row(selected)[1] == "2"


@pytest.mark.asyncio
async def test_status_pane_update_table_displays_unlinked_observations(
    status_session: tests.helpers.fixtures.peri_scribe.monitor.status_widgets.Session,
) -> None:
    session = status_session
    pane = session.app.query_one(peri_scribe.monitor.status_widgets.StatusPane)
    await tests.helpers.textual.invoke(
        pane.update_table,
        "recent",
        (
            peri_scribe.monitor.status.Metric(
                label="Unknown time",
                text="History unavailable",
                health=peri_scribe.monitor.status.Health.WARNING,
            ),
        ),
    )
    table = pane.query_one("#status-recent", textual.widgets.DataTable)
    assert table.row_count == 1
    assert not any(key[0] == "recent" for key in pane.targets)

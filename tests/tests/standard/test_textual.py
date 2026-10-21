"""Terminal test actions complete only after the corresponding real layout."""

import asyncio

import pytest
import textual.geometry

import tests.helpers.doubles.textual
import tests.helpers.textual


@pytest.mark.asyncio
async def test_session_resize_waits_for_screen_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.textual.ResizeApp(),
    ) as session:
        await session.refresh()
        screen = session.app.screen
        previous_size = screen.outer_size
        previous_region = session.app.query_one("#body").region
        target = textual.geometry.Size(80, 24)
        gate = tests.helpers.doubles.textual.ResizeGate(
            target=target,
            post_message=screen.post_message,
            resize_terminal=session.pilot.resize_terminal,
        )
        monkeypatch.setattr(screen, "post_message", gate.capture)
        monkeypatch.setattr(session.pilot, "resize_terminal", gate.observe)
        resizing = asyncio.create_task(session.resize(target.width, target.height))
        try:
            await asyncio.wait_for(gate.returned.wait(), 5)
            await session.refresh()
            assert session.app.size == target
            assert screen.size == target
            assert screen.outer_size == previous_size
            assert session.app.query_one("#body").region == previous_region
            assert len(gate.messages) == 1
            assert not resizing.done()
        finally:
            gate.release()
            await asyncio.wait_for(resizing, 5)
        assert screen.outer_size == target
        assert session.app.query_one("#body").region == target.region


@pytest.mark.asyncio
async def test_session_resize_completes_when_size_is_unchanged() -> None:
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.textual.ResizeApp(),
    ) as session:
        target = session.app.screen.outer_size
        await asyncio.wait_for(session.resize(target.width, target.height), 5)
        assert session.app.screen.outer_size == target
        assert session.app.query_one("#body").region == target.region


@pytest.mark.asyncio
async def test_session_resize_completes_each_sequential_layout() -> None:
    async with tests.helpers.textual.mounted(
        tests.helpers.doubles.textual.ResizeApp(),
    ) as session:
        for target in (
            textual.geometry.Size(80, 24),
            textual.geometry.Size(160, 50),
            textual.geometry.Size(120, 42),
        ):
            await asyncio.wait_for(session.resize(target.width, target.height), 5)
            assert session.app.screen.outer_size == target
            assert session.app.query_one("#body").region == target.region

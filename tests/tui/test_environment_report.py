"""Showing what loaded, from inside the app."""

import asyncio

from inshirah.core import Environment
from inshirah.tui.app import InshirahApp
from inshirah.tui.environment_report import EnvironmentReport

ENV = Environment.from_init(
    {
        "cwd": "/work/project",
        "skills": ["pangolin-facts"],
        "agents": ["scribe"],
        "tools": ["Read"],
        "mcp_servers": [{"name": "broken-one", "status": "failed"}],
    }
)


def test_nothing_is_known_before_the_first_turn():
    """init does not arrive until a turn starts, so neither does this."""
    known: list = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(120, 40)):
            known.append(app.conversation.environment)

    asyncio.run(scenario())
    assert known == [None]


def test_asking_before_the_first_turn_explains_why(monkeypatch):
    warned: list[tuple] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:
            monkeypatch.setattr(
                InshirahApp, "notify", lambda self, m, **kw: warned.append((m, kw))
            )
            await pilot.press("ctrl+i")
            await pilot.pause()

    asyncio.run(scenario())
    assert "send a message first" in warned[0][0]


def test_the_report_opens_once_something_is_known():
    opened: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:
            app.conversation._environment = ENV
            await pilot.press("ctrl+i")
            await pilot.pause()
            opened.append(type(app.screen).__name__)
            assert "pangolin-facts" in str(app.screen.query_one("#body").content)
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())
    assert opened == [EnvironmentReport.__name__]


def test_what_loaded_is_announced_once(monkeypatch):
    messages: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:
            monkeypatch.setattr(
                InshirahApp, "notify", lambda self, m, **kw: messages.append(m)
            )
            app.conversation._environment = ENV
            app._announce_environment()
            app._announce_environment()  # a second turn must not repeat it
            await pilot.pause()

    asyncio.run(scenario())
    assert sum("1 skills" in m for m in messages) == 1


def test_a_broken_mcp_server_is_called_out(monkeypatch):
    messages: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:
            monkeypatch.setattr(
                InshirahApp, "notify", lambda self, m, **kw: messages.append(m)
            )
            app.conversation._environment = ENV
            app._announce_environment()
            await pilot.pause()

    asyncio.run(scenario())
    assert any("broken-one" in m for m in messages)

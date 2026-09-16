"""The permission prompt.

Not optional decoration: with no ``can_use_tool`` callback the SDK raises
"canUseTool callback is not provided" in the middle of a turn the first time
Claude Code wants to ask about a command.
"""

import asyncio

from inshirah.tui import permissions
from inshirah.tui.app import InshirahApp


def test_every_conversation_is_born_with_a_permission_handler():
    """The registry hands it out, so a conversation created at any time has one."""
    app = InshirahApp()
    assert app.registry.can_use_tool is not None
    assert app.registry.create().can_use_tool is app.registry.can_use_tool


def test_threads_inherit_the_handler():
    conversation = InshirahApp().registry.create()
    assert conversation.thread_for("a1").can_use_tool is conversation.can_use_tool


def _press(*keys: str) -> str:
    """Answer the prompt with the keyboard instead of the mouse."""
    decisions: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:

            async def ask() -> None:
                result = await permissions.handler(app)("Write", {"file_path": "x.py"}, None)
                decisions.append(result.behavior)

            worker = app.run_worker(ask())
            await pilot.pause()
            for key in keys:
                await pilot.press(key)
            await pilot.pause()
            await asyncio.wait_for(worker.wait(), timeout=5)

    asyncio.run(scenario())
    return decisions[0]


def test_escape_denies():
    """Regression: the app's priority Escape binding swallowed this.

    The editing bindings are priority so a focused Input cannot eat them, but
    priority also outranks a screen's own bindings — Escape reached a no-op
    cancel_edit and the prompt hung with no way out but the mouse.
    """
    assert _press("escape") == "deny"


def test_allow_is_focused_so_enter_approves():
    assert _press("enter") == "allow"


def test_tabbing_moves_to_deny():
    assert _press("tab", "enter") == "deny"


def _answer(button: str) -> str:
    """Open the prompt, press a button, return what the callback decided.

    The handler runs inside a worker because ``push_screen_wait`` requires one —
    which is how it reaches it in the app, where sending is already a worker.
    """
    decisions: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:

            async def ask() -> None:
                result = await permissions.handler(app)(
                    "Bash", {"command": "rm -rf build"}, None
                )
                decisions.append(result.behavior)

            worker = app.run_worker(ask())
            await pilot.pause()
            await pilot.click(f"#{button}")
            await pilot.pause()
            await worker.wait()

    asyncio.run(scenario())
    return decisions[0]


def test_allowing_a_tool_returns_allow():
    assert _answer("allow") == "allow"


def test_denying_a_tool_returns_deny():
    assert _answer("deny") == "deny"


def test_a_denial_tells_the_model_why():
    """The model gets a reason, so it can adapt instead of retrying blindly."""
    messages: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:

            async def ask() -> None:
                result = await permissions.handler(app)("Bash", {"command": "x"}, None)
                messages.append(result.message)

            worker = app.run_worker(ask())
            await pilot.pause()
            await pilot.click("#deny")
            await pilot.pause()
            await worker.wait()

    asyncio.run(scenario())
    assert "Bash" in messages[0]


def test_the_prompt_shows_what_would_run():
    shown: list[str] = []

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(100, 40)) as pilot:
            screen = permissions.PermissionRequest("Bash", {"command": "rm -rf build"})
            await app.push_screen(screen)
            await pilot.pause()
            shown.append(str(app.screen.query_one("#detail").content))
            screen.dismiss(False)
            await pilot.pause()

    asyncio.run(scenario())
    assert "rm -rf build" in shown[0]

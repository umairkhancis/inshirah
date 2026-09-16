"""Slash commands in the TUI: offering them, completing them, running them.

The menu is the only part Inshirah owns. Execution is the CLI's, and the test
that matters most is the one asserting an ordinary command is sent through
untouched — expanding arguments here would be a second implementation of
something Claude Code already does.
"""

import asyncio

from conftest import COMMANDS, SESSION, assistant_entry, user_entry
from textual.widgets import Static

from inshirah.core import Conversation
from inshirah.tui.app import InshirahApp
from inshirah.tui.widgets import CommandMenu, CommandOption

KEY = {"project_key": "proj", "session_id": SESSION}


def run(scenario, monkeypatch=None):
    captured: dict = {"asked": []}

    async def fake_turn(self, prompt):
        captured["asked"].append(prompt)
        return None

    async def main() -> None:
        app = InshirahApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await app.workers.wait_for_complete()  # let discovery settle
            await pilot.pause()
            await scenario(app, pilot, captured)

    if monkeypatch is not None:
        monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(main())
    return captured


def menu_of(app):
    return app.main_pane.composer.menu


def names(app):
    return [o.command.name for o in app.main_pane.composer.query(CommandOption)]


# --- discovery -----------------------------------------------------------


def test_the_commands_come_from_the_cli_not_from_us():
    async def scenario(app, pilot, out):
        out["known"] = [c.name for c in app.conversation.commands]

    assert run(scenario)["known"] == [c.name for c in COMMANDS]


def test_both_composers_are_told_what_exists():
    """A thread can run a command too; it is a conversation, not a reply box."""

    async def scenario(app, pilot, out):
        out["main"] = len(app.main_pane.composer.commands)
        out["thread"] = len(app.thread_pane.composer.commands)

    result = run(scenario)
    assert result["main"] == result["thread"] == len(COMMANDS)


# --- the menu ------------------------------------------------------------


def test_typing_a_slash_offers_every_command():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/"
        await pilot.pause()
        out["shown"] = names(app)
        out["open"] = menu_of(app).visible_menu

    result = run(scenario)
    assert result["open"] is True
    assert result["shown"] == [c.name for c in COMMANDS]


def test_typing_narrows_it():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/co"
        await pilot.pause()
        out["shown"] = names(app)

    assert run(scenario)["shown"] == ["compact", "context"]


def test_the_menu_closes_once_you_reach_the_arguments():
    """After the space the rest belongs to the command, not to the menu."""

    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/zorblat"
        await pilot.pause()
        out["while_naming"] = menu_of(app).visible_menu
        app.main_pane.composer.input.value = "/zorblat wid"
        await pilot.pause()
        out["while_arguing"] = menu_of(app).visible_menu

    result = run(scenario)
    assert result["while_naming"] is True
    assert result["while_arguing"] is False


def test_an_ordinary_message_never_opens_the_menu():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "what is an index?"
        await pilot.pause()
        out["open"] = menu_of(app).visible_menu

    assert run(scenario)["open"] is False


def test_arrows_move_the_highlight_without_leaving_the_input():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/co"
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        out["picked"] = menu_of(app).current.name
        out["still_typing"] = app.focused is app.main_pane.composer.input

    result = run(scenario)
    assert result["picked"] == "context"
    assert result["still_typing"] is True


def test_tab_completes_the_name_and_waits_for_arguments():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/zor"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        out["value"] = app.main_pane.composer.input.value
        out["open"] = menu_of(app).visible_menu

    result = run(scenario)
    assert result["value"] == "/zorblat "  # trailing space: it takes an argument
    assert result["open"] is False


def test_completing_a_command_that_takes_nothing_leaves_no_space():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/cont"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        out["value"] = app.main_pane.composer.input.value

    assert run(scenario)["value"] == "/context"


def test_enter_completes_rather_than_sending_while_the_menu_is_open(monkeypatch):
    """Otherwise picking a command would fire a half-typed one at the model."""

    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/zor"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        out["value"] = app.main_pane.composer.input.value

    result = run(scenario, monkeypatch)
    assert result["value"] == "/zorblat "
    assert result["asked"] == []  # nothing was sent


def test_escape_closes_the_menu_instead_of_the_thread():
    """The app's priority escape binding would otherwise swallow it."""

    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(
            KEY, [user_entry("u1", "hi"), assistant_entry("a1", "hello")]
        )
        app.conversation._sync()
        await app.refresh_all()
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()

        app.thread_pane.composer.input.value = "/co"
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        out["menu_open"] = app.thread_pane.composer.menu.visible_menu
        out["thread_still_open"] = app.thread is not None

    result = run(scenario)
    assert result["menu_open"] is False
    assert result["thread_still_open"] is True


def test_clicking_a_command_completes_it():
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/"
        await pilot.pause()
        option = [o for o in app.main_pane.composer.query(CommandOption)
                  if o.command.name == "context"][0]
        option.post_message(CommandMenu.Picked(option.command))
        await pilot.pause()
        out["value"] = app.main_pane.composer.input.value

    assert run(scenario)["value"] == "/context"


# --- execution -----------------------------------------------------------


def test_an_ordinary_command_is_sent_through_untouched(monkeypatch):
    """The CLI expands $ARGUMENTS, ! blocks and @file, exactly as under claude."""

    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/zorblat widget --flag"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert run(scenario, monkeypatch)["asked"] == ["/zorblat widget --flag"]


def test_an_unknown_command_is_still_the_cli_s_to_answer(monkeypatch):
    """It replies "Unknown command: /x"; second-guessing it would diverge."""

    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/nosuchthing"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert run(scenario, monkeypatch)["asked"] == ["/nosuchthing"]


def test_slash_clear_starts_a_new_conversation_here(monkeypatch):
    """The CLI's /clear swaps its session silently, which would look like a
    freeze; the same idea on this surface is a new conversation."""

    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(KEY, [user_entry("u1", "first thing")])
        app.conversation._sync()
        await app.refresh_all()
        first = app.conversation.id

        app.main_pane.composer.input.value = "/clear"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["switched"] = app.conversation.id != first
        out["empty"] = len(app.conversation.turns)
        out["kept"] = len(app.registry.listing())

    result = run(scenario, monkeypatch)
    assert result["switched"] is True
    assert result["empty"] == 0
    assert result["kept"] == 2  # the previous one stays, as the CLI's does
    assert result["asked"] == []  # never reached the model


def test_slash_clear_can_name_the_new_conversation(monkeypatch):
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/clear release notes"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["name"] = app.conversation.display_name()

    assert run(scenario, monkeypatch)["name"] == "release notes"


def test_slash_rename_names_the_conversation(monkeypatch):
    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/rename Index research"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["name"] = app.conversation.display_name()
        out["header"] = str(app.main_pane.query_one(".pane-title", Static).content)

    result = run(scenario, monkeypatch)
    assert result["name"] == "Index research"
    assert result["header"] == "# Index research"
    assert result["asked"] == []


def test_a_command_works_from_inside_a_thread(monkeypatch):
    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(
            KEY, [user_entry("u1", "hi"), assistant_entry("a1", "hello")]
        )
        app.conversation._sync()
        await app.refresh_all()
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()

        app.thread_pane.composer.input.value = "/context"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert run(scenario, monkeypatch)["asked"] == ["/context"]


# --- what a command leaves on screen -------------------------------------

from conftest import command_entry, command_output_entry, meta_entry  # noqa: E402


def test_a_command_and_its_output_are_shown_not_its_plumbing():
    """Reported: the transcript showed <local-command-caveat> and
    <command-name> tags, and the command's output was missing entirely."""

    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(
            KEY,
            [
                meta_entry("m1", "<local-command-caveat>Caveat: …</local-command-caveat>"),
                command_entry("c1", "/model"),
                command_output_entry("c2", "Current model: `Opus 5`"),
            ],
        )
        app.conversation._sync()
        await app.refresh_all()
        out["rows"] = [(r.role, r.author, r.body_text) for r in app.main_pane.rows]

    assert run(scenario)["rows"] == [
        ("user", "you", "/model"),
        ("command", "command", "Current model: `Opus 5`"),
    ]


def test_command_output_is_shown_verbatim():
    """A usage line like "/model <name>" must survive; markdown would eat the tag."""

    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(
            KEY, [command_output_entry("c1", "Usage: /model <name>. Try opus[1m].")]
        )
        app.conversation._sync()
        await app.refresh_all()
        row = app.main_pane.rows[0]
        out["body"] = str(row.query_one(".body", Static).content)

    assert run(scenario)["body"] == "Usage: /model <name>. Try opus[1m]."


def test_command_output_is_not_something_you_rewrite():
    notes: list[str] = []

    async def scenario(app, pilot, out):
        app.conversation.session_id = SESSION
        await app.conversation.store.append(
            KEY, [command_entry("c1", "/model"), command_output_entry("c2", "Opus 5")]
        )
        app.conversation._sync()
        await app.refresh_all()
        app.notify = lambda m, **kw: notes.append(m)
        app.main_pane.select(app.main_pane.rows[-1])
        await pilot.press("ctrl+e")
        await pilot.pause()
        out["editor"] = app.editor

    assert run(scenario)["editor"] is None
    assert any("command's output" in n for n in notes)


# --- how many keypresses a command costs ---------------------------------


def test_one_enter_runs_a_command_that_needs_no_arguments(monkeypatch):
    """Reported: it took three — one to pick, one to dismiss the menu it
    reopened on its own result, and one to send."""

    async def scenario(app, pilot, out):
        composer = app.main_pane.composer
        composer.input.value = "/cont"
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["value"] = composer.input.value
        out["menu"] = composer.menu.visible_menu

    result = run(scenario, monkeypatch)
    assert result["asked"] == ["/context"]  # one press was enough
    assert result["value"] == ""
    assert result["menu"] is False


def test_enter_waits_when_the_command_still_needs_arguments(monkeypatch):
    """Sending "/zorblat" with no component would just waste a turn."""

    async def scenario(app, pilot, out):
        composer = app.main_pane.composer
        composer.input.value = "/zor"
        await pilot.pause()
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["value"] = composer.input.value
        out["menu"] = composer.menu.visible_menu

    result = run(scenario, monkeypatch)
    assert result["asked"] == []
    assert result["value"] == "/zorblat "
    assert result["menu"] is False  # and it does not reopen on its own result


def test_a_completed_command_then_sends_on_the_next_enter(monkeypatch):
    async def scenario(app, pilot, out):
        composer = app.main_pane.composer
        composer.input.value = "/zor"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        composer.input.value = "/zorblat widget"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

    assert run(scenario, monkeypatch)["asked"] == ["/zorblat widget"]


def test_tab_completes_without_running(monkeypatch):
    """Tab is for finishing the name; enter is for meaning it."""

    async def scenario(app, pilot, out):
        composer = app.main_pane.composer
        composer.input.value = "/cont"
        await pilot.pause()
        await pilot.press("tab")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["value"] = composer.input.value
        out["menu"] = composer.menu.visible_menu

    result = run(scenario, monkeypatch)
    assert result["asked"] == []
    assert result["value"] == "/context"
    assert result["menu"] is False  # the completion must not re-offer itself


def test_editing_a_completed_command_offers_the_menu_again(monkeypatch):
    """Suppressing the reopen must not mean suppressing it forever."""

    async def scenario(app, pilot, out):
        composer = app.main_pane.composer
        composer.input.value = "/cont"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        composer.input.value = "/co"  # backed up to type something else
        await pilot.pause()
        out["menu"] = composer.menu.visible_menu
        out["shown"] = names(app)

    result = run(scenario, monkeypatch)
    assert result["menu"] is True
    assert result["shown"] == ["compact", "context"]


# --- the menu survives changing conversation ------------------------------


async def _menu_still_works(app, pilot) -> int:
    app.main_pane.composer.input.value = "/"
    await pilot.pause()
    await pilot.pause()
    return len(app.main_pane.composer.query(CommandOption))


def test_the_menu_still_works_after_slash_clear(monkeypatch):
    """Reported: after /clear the dropdown was gone until a restart.

    The commands are the project's, but they were being kept on the
    conversation — so a brand new one started with none."""

    async def scenario(app, pilot, out):
        app.main_pane.composer.input.value = "/clear"
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["offered"] = await _menu_still_works(app, pilot)

    assert run(scenario, monkeypatch)["offered"] == len(COMMANDS)


def test_the_menu_still_works_in_a_brand_new_conversation():
    async def scenario(app, pilot, out):
        await app.action_new_conversation()
        await pilot.pause()
        out["offered"] = await _menu_still_works(app, pilot)

    assert run(scenario)["offered"] == len(COMMANDS)


def test_the_menu_still_works_after_switching_conversations():
    from inshirah.tui.widgets import RailItem

    async def scenario(app, pilot, out):
        first = app.conversation.id
        await app.action_new_conversation()
        await pilot.pause()
        app.query(RailItem).first().post_message(RailItem.Chosen(first))
        await pilot.pause()
        out["offered"] = await _menu_still_works(app, pilot)

    assert run(scenario)["offered"] == len(COMMANDS)

"""The TUI's routing decisions, with the model stubbed out.

Editing a question and editing a reply take different paths, and the choice is
made in the app — so testing the conversation layer alone leaves the decision
itself unguarded.
"""

import asyncio

from conftest import SESSION, assistant_entry, user_entry
from textual.widgets import TextArea

from inshirah.core import Conversation
from inshirah.tui.app import InshirahApp

KEY = {"project_key": "proj", "session_id": SESSION}


async def seed(app, turns=None) -> None:
    app.conversation.session_id = SESSION
    await app.conversation.store.append(
        KEY,
        turns
        or [
            user_entry("u1", "Invent a codename."),
            assistant_entry("a1", "Falcon"),
        ],
    )
    app.conversation._sync()
    await app.refresh_all()


def drive(monkeypatch, *, edit_index: int, new_text: str) -> list[tuple]:
    """Seed a conversation, edit the message at ``edit_index``, record the call."""
    calls: list[tuple] = []

    async def fake_resend(self, uuid, text):
        calls.append(("resend", uuid, text))
        return None

    def fake_edit(self, uuid, text):
        calls.append(("edit", uuid, text))
        return 0

    monkeypatch.setattr(Conversation, "edit_and_resend", fake_resend)
    monkeypatch.setattr(Conversation, "edit", fake_edit)

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await seed(app)

            rows = [r for r in app.main_pane.rows if r.uuid]
            app.main_pane.select(rows[edit_index])
            await pilot.press("ctrl+e")
            await pilot.pause()
            app.query_one("#editor", TextArea).text = new_text
            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()

    asyncio.run(scenario())
    return calls


def test_saving_an_edited_question_resends_it(monkeypatch):
    """The reported bug: the edit was saved but never asked."""
    calls = drive(monkeypatch, edit_index=0, new_text="Invent a planet name.")
    assert calls == [("resend", "u1", "Invent a planet name.")]


def test_saving_an_edited_reply_does_not_resend(monkeypatch):
    """A rewritten answer replaces what was said — asking again would undo it."""
    calls = drive(monkeypatch, edit_index=1, new_text="Petra")
    assert calls == [("edit", "a1", "Petra")]


def test_the_pane_header_names_the_conversation_and_the_thread():
    """The two panes each say what they are showing; neither invents the name."""
    seen: dict = {}

    async def scenario() -> None:
        app = InshirahApp()
        async with app.run_test(size=(140, 40)) as pilot:
            await seed(
                app,
                [
                    user_entry("u1", "What is an index?"),
                    assistant_entry("a1", "An index speeds up lookups."),
                ],
            )
            seen["conversation"] = str(
                app.main_pane.query_one(".pane-title").content
            )
            seen["window_title"] = app.sub_title

            row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
            await app.open_thread_on(app.main_pane, row)
            await pilot.pause()
            seen["thread"] = str(app.thread_pane.query_one(".pane-title").content)

    asyncio.run(scenario())
    # Both names come from the core, so an export and the screen cannot disagree.
    assert seen["conversation"] == "# What is an index?"
    assert seen["window_title"] == "What is an index?"
    assert seen["thread"] == "⤷ What is an index?"

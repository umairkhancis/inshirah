"""The Slack-shaped surface: the rail, the thread column, and the landing.

Not a test of the stylesheet. These are the behaviours the layout promises —
that a thread opens *beside* the conversation rather than replacing it, that the
rail is navigation, and that an empty app tells you what to do.
"""

import asyncio

from conftest import SESSION, assistant_entry, user_entry
from textual.widgets import Static, TextArea

from inshirah.core import FileStorage
from inshirah.tui import design
from inshirah.tui.app import InshirahApp
from inshirah.tui.widgets import MessageRow, RailItem, Starter

KEY = {"project_key": "proj", "session_id": SESSION}


def run(scenario, storage=None):
    captured: dict = {}

    async def main() -> None:
        app = InshirahApp(storage=storage)
        async with app.run_test(size=(140, 40)) as pilot:
            await scenario(app, pilot, captured)

    asyncio.run(main())
    return captured


async def seed(app, text="What is an index?") -> None:
    app.conversation.session_id = SESSION
    await app.conversation.store.append(
        KEY, [user_entry("u1", text), assistant_entry("a1", "An index speeds up lookups.")]
    )
    app.conversation._sync()
    await app.refresh_all()


# --- landing -------------------------------------------------------------


def test_an_empty_app_welcomes_you_rather_than_blinking():
    async def scenario(app, pilot, out):
        out["welcome"] = bool(app.query("#welcome"))
        out["starters"] = len(app.query(Starter))

    result = run(scenario)
    assert result["welcome"] is True
    assert result["starters"] == len(app_starters())


def app_starters():
    from inshirah.tui.widgets import Welcome

    return Welcome.STARTERS


def test_clicking_a_starter_loads_it_into_the_composer():
    """The fastest way to learn what the surface does is to watch it do something."""

    async def scenario(app, pilot, out):
        starter = app.query(Starter).first()
        await pilot.click(Starter)
        await pilot.pause()
        out["value"] = app.main_pane.composer.input.value
        out["expected"] = starter.prompt

    result = run(scenario)
    assert result["value"] == result["expected"] != ""


def test_the_welcome_makes_way_once_there_is_a_conversation():
    async def scenario(app, pilot, out):
        await seed(app)
        out["welcome"] = bool(app.query("#welcome"))

    assert run(scenario)["welcome"] is False


# --- the rail ------------------------------------------------------------


def test_the_rail_lists_conversations_and_marks_the_one_you_are_in():
    async def scenario(app, pilot, out):
        await seed(app)
        await app.action_new_conversation()
        await pilot.pause()
        items = list(app.query(RailItem))
        out["names"] = [item.summary["name"] for item in items]
        out["current"] = [i.summary["name"] for i in items if i.has_class("current")]

    result = run(scenario)
    assert set(result["names"]) == {"What is an index?", "New conversation"}
    assert result["current"] == ["New conversation"]  # the one just created


def test_a_new_conversation_starts_empty_and_separate():
    async def scenario(app, pilot, out):
        await seed(app)
        first = app.conversation.id
        await app.action_new_conversation()
        await pilot.pause()
        out["same"] = app.conversation.id == first
        out["turns"] = len(app.conversation.turns)
        out["welcome"] = bool(app.query("#welcome"))

    result = run(scenario)
    assert result["same"] is False
    assert result["turns"] == 0
    assert result["welcome"] is True


def test_clicking_the_rail_switches_conversation():
    """The rail is navigation, not an ornament."""

    async def scenario(app, pilot, out):
        await seed(app)
        first = app.conversation.id
        await app.action_new_conversation()
        await pilot.pause()

        target = [i for i in app.query(RailItem) if i.tree_id == first][0]
        target.post_message(RailItem.Chosen(first))
        await pilot.pause()
        out["back"] = app.conversation.id == first
        out["name"] = str(app.main_pane.query_one(".pane-title").content)

    result = run(scenario)
    assert result["back"] is True
    assert result["name"] == "# What is an index?"


def test_conversations_survive_a_restart(tmp_path):
    """Two apps over one directory, as a quit and a relaunch would be."""

    async def first(app, pilot, out):
        await seed(app, "Release checklist question")
        app.registry.save(app.conversation)
        out["id"] = app.conversation.id

    created = run(first, storage=FileStorage(tmp_path))

    async def second(app, pilot, out):
        out["id"] = app.conversation.id
        out["name"] = app.conversation.display_name()
        out["turns"] = len(app.conversation.turns)

    reopened = run(second, storage=FileStorage(tmp_path))
    assert reopened["id"] == created["id"]
    assert reopened["name"] == "Release checklist question"
    assert reopened["turns"] == 2


# --- the thread column ---------------------------------------------------


def test_a_thread_opens_beside_the_conversation_not_over_it():
    """The whole reason it is a column: going deep must not cost you the context."""

    async def scenario(app, pilot, out):
        await seed(app)
        out["hidden_before"] = app.thread_pane.has_class("hidden")

        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()
        out["hidden_after"] = app.thread_pane.has_class("hidden")
        out["main_still_there"] = [r.uuid for r in app.main_pane.rows]

    result = run(scenario)
    assert result["hidden_before"] is True
    assert result["hidden_after"] is False
    assert result["main_still_there"] == ["u1", "a1"]


def test_the_thread_opens_on_the_message_it_hangs_off():
    """A reply needs something to be a reply to — the same orientation Slack gives."""

    async def scenario(app, pilot, out):
        await seed(app)
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()
        out["first"] = app.thread_pane.rows[0].body_text
        out["divider"] = str(
            app.thread_pane.query_one(".thread-divider", Static).content
        )

    result = run(scenario)
    assert result["first"] == "An index speeds up lookups."
    assert "no replies yet" in result["divider"]


def test_the_reply_count_is_what_you_click():
    """And it counts replies, not the context the fork copied in."""

    async def scenario(app, pilot, out):
        await seed(app)
        thread = app.conversation.thread_for("a1")
        thread.session_id = "thread-session"
        await thread.store.append(
            THREAD_KEY,
            [
                user_entry("u1", "What is an index?"),  # copied in by the fork
                assistant_entry("a1", "An index speeds up lookups."),  # copied in
                user_entry("t1", "why?"),  # the one actual reply
            ],
        )
        thread._sync()
        await app.refresh_all()
        await pilot.pause()
        out["shown"] = [str(s.content) for s in app.main_pane.query(".replies")]
        await pilot.click(".replies")
        await pilot.pause()
        out["opened"] = app.thread is not None

    result = run(scenario)
    assert result["shown"] == ["⤷ 1 reply"]
    assert result["opened"] is True


def test_closing_the_thread_leaves_the_conversation_where_it_was():
    async def scenario(app, pilot, out):
        await seed(app)
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        out["thread"] = app.thread
        out["hidden"] = app.thread_pane.has_class("hidden")
        out["main"] = [r.uuid for r in app.main_pane.rows]

    result = run(scenario)
    assert result["thread"] is None
    assert result["hidden"] is True
    assert result["main"] == ["u1", "a1"]


def test_a_thread_inside_a_thread_steps_back_one_level_at_a_time():
    """Threads nest as deep as you like, so leaving one must not drop you home."""

    async def scenario(app, pilot, out):
        await started_thread(app, pilot)

        deep_row = [r for r in app.thread_pane.rows if r.uuid == "t2"][0]
        await app.open_thread_on(app.thread_pane, deep_row)
        await pilot.pause()
        out["depth_deep"] = app.thread.depth

        await app.close_thread()
        out["depth_back"] = app.thread.depth if app.thread else None

        await app.close_thread()
        out["closed"] = app.thread is None

    result = run(scenario)
    assert result["depth_deep"] == 2
    assert result["depth_back"] == 1
    assert result["closed"] is True


# --- themes --------------------------------------------------------------


def test_both_themes_apply_without_a_missing_token():
    """A token the stylesheet uses but a theme does not define fails at swap."""

    async def scenario(app, pilot, out):
        out["start"] = app.theme
        for theme in design.THEMES:
            app.theme = theme.name
            await pilot.pause()
        out["end"] = app.theme

    result = run(scenario)
    assert result["start"] == design.DUSK.name
    assert result["end"] == design.DAY.name


# --- naming --------------------------------------------------------------


def test_renaming_a_conversation_sticks_in_the_rail():
    """Naming itself after the first question is right until the topic moves on."""

    async def scenario(app, pilot, out):
        await seed(app)
        app.action_rename()
        await pilot.pause()
        out["prefilled"] = app.screen.query_one("#name").value
        app.screen.query_one("#name").value = "Index research"
        await pilot.press("enter")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        out["header"] = str(app.main_pane.query_one(".pane-title").content)
        out["rail"] = [i.summary["name"] for i in app.query(RailItem)]

    result = run(scenario)
    assert result["prefilled"] == "What is an index?"
    assert result["header"] == "# Index research"
    assert result["rail"] == ["Index research"]


def test_cancelling_a_rename_changes_nothing():
    async def scenario(app, pilot, out):
        await seed(app)
        app.action_rename()
        await pilot.pause()
        app.screen.query_one("#name").value = "discarded"
        await pilot.press("escape")
        await pilot.pause()
        await app.workers.wait_for_complete()
        out["name"] = app.conversation.display_name()

    assert run(scenario)["name"] == "What is an index?"


# --- reported bugs -------------------------------------------------------

THREAD_KEY = {"project_key": "proj", "session_id": "thread-session"}


async def started_thread(app, pilot):
    """Open a thread off a1 and give it the transcript a real fork would have."""
    await seed(app)
    row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
    await app.open_thread_on(app.main_pane, row)
    await pilot.pause()
    thread = app.thread
    thread.session_id = "thread-session"
    await thread.store.append(
        THREAD_KEY,
        [
            user_entry("u1", "What is an index?"),  # copied in by the fork
            assistant_entry("a1", "An index speeds up lookups."),  # copied in
            user_entry("t1", "Why not a hash?"),  # said in the thread
            assistant_entry("t2", "Ranges."),  # said in the thread
        ],
    )
    thread._sync()
    await app.refresh_all()
    await pilot.pause()
    return thread


def test_a_thread_shows_only_what_was_said_in_it():
    """Reported: after replying in a thread, the whole main conversation appeared.

    The branch-point message stays at the top for orientation — that is what you
    are replying to — but everything before it is context, not reading material.
    """

    async def scenario(app, pilot, out):
        await started_thread(app, pilot)
        out["rows"] = [(r.uuid, r.branch) for r in app.thread_pane.rows]

    assert run(scenario)["rows"] == [("a1", True), ("t1", False), ("t2", False)]


def test_the_hidden_messages_are_still_sent_to_the_model():
    """Hiding them is a reading decision; the thread's context is untouched."""

    async def scenario(app, pilot, out):
        thread = await started_thread(app, pilot)
        out["context"] = [t.text for t in thread.turns]
        out["shown"] = [t.text for t in thread.own_turns]

    result = run(scenario)
    assert "What is an index?" in result["context"]
    assert "What is an index?" not in result["shown"]


def test_the_divider_counts_the_thread_not_the_context():
    async def scenario(app, pilot, out):
        await started_thread(app, pilot)
        out["divider"] = str(app.thread_pane.query_one(".thread-divider", Static).content)

    assert "2 replies" in run(scenario)["divider"]


def test_the_branch_point_message_cannot_be_threaded_off_again():
    """It belongs to the parent; branching off it would hang a thread on a
    message this conversation does not have."""

    async def scenario(app, pilot, out):
        await seed(app)
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)
        await pilot.pause()
        empty = app.thread
        out["rows"] = [r.uuid for r in app.thread_pane.rows]
        out["target"] = app.pane.target()

        await pilot.press("ctrl+t")
        await pilot.pause()
        out["nested"] = list(empty.threads)
        out["depth"] = app.thread.depth

    result = run(scenario)
    assert result["rows"] == ["a1"]  # only the branch point is on screen
    assert result["target"] is None  # so there is nothing for ctrl+t to act on
    assert result["nested"] == []  # and no bogus thread was created
    assert result["depth"] == 1  # still in the thread we opened


def test_a_thread_can_still_be_threaded_off_its_own_messages():
    """The guard must not cost us nesting, which is the point of threads here."""

    async def scenario(app, pilot, out):
        thread = await started_thread(app, pilot)
        await pilot.press("ctrl+t")
        await pilot.pause()
        out["nested"] = list(thread.threads)
        out["depth"] = app.thread.depth

    result = run(scenario)
    assert result["nested"] == ["t2"]  # the last message said in the thread
    assert result["depth"] == 2


def test_export_is_offered_rather_than_hidden():
    """Reported as 'pressing ctrl+t does not export' — the one key that writes a
    file was not shown anywhere, so there was nothing to press."""
    shown = {b.key for b in InshirahApp.BINDINGS if b.show}
    assert "ctrl+x" in shown


def test_exporting_from_inside_a_thread_writes_the_whole_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    async def scenario(app, pilot, out):
        await started_thread(app, pilot)
        app.action_export()
        await pilot.pause()
        out["text"] = (tmp_path / "exports" / "latest.md").read_text()

    text = run(scenario)["text"]
    assert "Why not a hash?" in text  # what was said in the thread
    assert "inherited" in text  # and the context it was said against


def test_editing_the_parent_does_not_rewrite_the_thread_on_screen():
    """Reported: editing the main conversation changed the thread's first message."""

    async def scenario(app, pilot, out):
        await started_thread(app, pilot)
        app.conversation.edit("a1", "REWRITTEN in the main conversation")
        await app.refresh_all()
        await pilot.pause()
        out["branch_row"] = app.thread_pane.rows[0].body_text
        out["main_row"] = [
            r.body_text for r in app.main_pane.rows if r.uuid == "a1"
        ][0]

    result = run(scenario)
    assert result["main_row"] == "REWRITTEN in the main conversation"
    assert result["branch_row"] == "An index speeds up lookups."


def test_an_edit_that_strands_a_thread_says_so_and_closes_the_pane():
    """Losing a thread off screen without a word would be worse than the edit."""
    notes: list[str] = []

    async def scenario(app, pilot, out):
        await seed(app)
        row = [r for r in app.main_pane.rows if r.uuid == "a1"][0]
        await app.open_thread_on(app.main_pane, row)  # opened but never used
        await pilot.pause()
        app.notify = lambda m, **kw: notes.append(m)

        target = [r for r in app.main_pane.rows if r.uuid == "u1"][0]
        target.post_message(MessageRow.Selected(target))
        await pilot.pause()
        await pilot.press("ctrl+e")
        await pilot.pause()
        app.query_one("#editor", TextArea).text = "A different question"
        await pilot.press("ctrl+s")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

        out["threads"] = list(app.conversation.threads)
        out["pane_closed"] = app.thread is None
        out["hidden"] = app.thread_pane.has_class("hidden")

    result = run(scenario)
    assert result["threads"] == []  # the empty thread had nothing left to fork from
    assert result["pane_closed"] is True
    assert result["hidden"] is True
    assert any("empty thread(s) dropped" in n for n in notes)

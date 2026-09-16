"""What a sidebar full of conversations needs from the core.

Naming, ordering and durability of *conversations* — as opposed to threads,
which are named by what they hang off and tested in test_snapshot.py. The
distinction is the point: a tree has one name however deep you are inside it.
"""

import asyncio

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import (
    Conversation,
    ConversationBusy,
    ConversationNotFound,
    ConversationRegistry,
    FileStorage,
    Harness,
    MemoryStorage,
)

KEY = {"project_key": "proj", "session_id": SESSION}


def seeded(text: str = "What is an index?") -> Conversation:
    c = Conversation()
    c.session_id = SESSION
    asyncio.run(c.store.append(KEY, [user_entry("u1", text), assistant_entry("a1", "Sure.")]))
    c._sync()
    return c


# --- naming --------------------------------------------------------------


def test_an_untouched_conversation_says_it_is_new():
    """The sidebar has to draw it before anything has been asked."""
    assert Conversation().display_name() == "New conversation"


def test_a_conversation_is_named_by_what_was_first_asked():
    assert seeded().display_name() == "What is an index?"


def test_an_explicit_name_wins():
    tree = seeded()
    tree.name = "Index research"
    assert tree.display_name() == "Index research"


def test_the_name_is_trimmed_to_fit():
    tree = seeded("a question that runs on well past any sidebar width at all")
    assert tree.display_name(12) == "a question t"


def test_every_thread_reports_the_conversation_it_belongs_to():
    """A thread is not a separate conversation, however deep it goes."""
    tree = seeded()
    deep = tree.thread_for("a1").thread_for("x")
    assert deep.display_name() == tree.display_name() == "What is an index?"


def test_a_thread_is_still_named_by_what_it_hangs_off():
    """display_name and title answer different questions; neither replaced the other."""
    tree = seeded()
    thread = tree.thread_for("a1")
    assert thread.title() == "What is an index?"
    assert tree.title() == "main"  # the breadcrumb root is unchanged


# --- ordering ------------------------------------------------------------


def test_using_a_conversation_moves_it_up_the_list():
    registry = ConversationRegistry()
    first, second = registry.create(), registry.create()
    assert [s["id"] for s in registry.listing()] == [second.id, first.id]

    first._sync()  # every transcript change funnels through here
    assert [s["id"] for s in registry.listing()][0] == first.id


def test_the_listing_describes_each_conversation():
    registry = ConversationRegistry()
    tree = registry.create()
    tree.session_id = SESSION
    asyncio.run(tree.store.append(KEY, [user_entry("u1", "Ship it?"), assistant_entry("a1", "Yes.")]))
    tree._sync()
    tree.thread_for("a1")

    entry = registry.listing()[0]
    assert entry["name"] == "Ship it?"
    assert entry["messages"] == 2
    assert entry["threads"] == 1
    assert entry["named"] is False


def test_renaming_marks_it_as_named():
    registry = ConversationRegistry()
    tree = registry.create()
    registry.rename(tree.id, "  Release checklist  ")
    entry = registry.listing()[0]
    assert (entry["name"], entry["named"]) == ("Release checklist", True)


def test_clearing_a_name_goes_back_to_the_derived_one():
    registry = ConversationRegistry()
    tree = registry.create(name="Temporary")
    registry.rename(tree.id, "   ")
    assert registry.listing()[0]["name"] == "New conversation"


# --- removing ------------------------------------------------------------


def test_deleting_takes_a_conversation_out_of_the_listing():
    registry = ConversationRegistry()
    keep, drop = registry.create(name="Keep"), registry.create(name="Drop")
    registry.delete(drop.id)
    assert [s["name"] for s in registry.listing()] == ["Keep"]


def test_deleting_takes_the_file_with_it(tmp_path):
    """Gone from the rail is not enough — a relaunch reads the directory."""
    storage = FileStorage(tmp_path)
    tree = ConversationRegistry(storage).create()
    ConversationRegistry(storage).delete(tree.id)
    assert list(tmp_path.glob("*.json")) == []
    assert ConversationRegistry(FileStorage(tmp_path)).listing() == []


def test_deleting_forgets_the_live_copy_too():
    """Left live, the next get() would hand back a conversation with no file."""
    registry = ConversationRegistry()
    tree = registry.create()
    registry.delete(tree.id)
    with pytest.raises(ConversationNotFound):
        registry.get(tree.id)


def test_a_conversation_mid_turn_is_not_deleted_underneath_it():
    """The turn saves the tree when it ends, which would write the file back."""
    registry = ConversationRegistry()
    tree = registry.create()

    async def while_a_turn_holds_the_lock() -> None:
        async with tree.root._lock:
            with pytest.raises(ConversationBusy):
                registry.delete(tree.id)

    asyncio.run(while_a_turn_holds_the_lock())
    assert [s["id"] for s in registry.listing()] == [tree.id]


def test_deleting_what_is_not_there_is_not_an_error():
    """Two rails over one directory, or a second click on the same ✕."""
    registry = ConversationRegistry()
    registry.delete("nothing-by-that-name")


# --- durability ----------------------------------------------------------


def test_a_name_survives_a_restart(tmp_path):
    storage = FileStorage(tmp_path)
    first = ConversationRegistry(storage)
    tree = first.create(name="Release checklist")

    reopened = ConversationRegistry(FileStorage(tmp_path)).get(tree.id)
    assert reopened.display_name() == "Release checklist"


def test_reopening_a_conversation_does_not_look_like_using_it(tmp_path):
    """Loading stamps _sync; without care every restart would reorder the list."""
    storage = FileStorage(tmp_path)
    tree = ConversationRegistry(storage).create()
    tree.updated = 1_000.0
    ConversationRegistry(storage).save(tree)

    reopened = ConversationRegistry(FileStorage(tmp_path)).get(tree.id)
    assert reopened.updated == 1_000.0


def test_a_restored_conversation_can_still_run_a_turn():
    """Without the harness and the prompt callback it would have neither tools
    nor any way to ask — a conversation resumed after a restart would be inert."""
    harness = Harness(permission_mode="plan")

    async def prompt(*args):  # stand-in for the TUI's permission screen
        return None

    storage = MemoryStorage()
    created = ConversationRegistry(storage).create()
    created.thread_for("a1")  # a thread has to be adopted too
    ConversationRegistry(storage).save(created)

    registry = ConversationRegistry(storage, harness=harness, can_use_tool=prompt)
    restored = registry.get(created.id)
    assert restored.harness is harness
    assert restored.thread_for("a1").can_use_tool is prompt


def test_a_new_conversation_is_born_with_the_session_harness():
    harness = Harness(permission_mode="plan")
    registry = ConversationRegistry(harness=harness)
    assert registry.create().harness is harness


def test_a_missing_conversation_is_skipped_rather_than_fatal():
    """ids() and get() race; a listing that raises would empty the sidebar."""
    registry = ConversationRegistry()
    tree = registry.create()
    registry.storage.delete(tree.id)
    registry._live.pop(tree.id)
    assert registry.listing() == []


@pytest.mark.parametrize("name", ["", "   ", None])
def test_a_blank_name_is_no_name(name):
    registry = ConversationRegistry()
    tree = registry.create()
    registry.rename(tree.id, name)
    assert tree.name is None


# --- naming ignores what is not a message --------------------------------


def test_a_conversation_is_not_named_after_a_slash_command():
    """Reported: running /config first named the conversation "/config"."""
    from conftest import command_entry, command_output_entry

    c = Conversation()
    c.session_id = SESSION
    asyncio.run(
        c.store.append(
            KEY,
            [
                command_entry("c1", "/config"),
                command_output_entry("c2", "Usage: /config key=value"),
                user_entry("u1", "Now the actual question"),
            ],
        )
    )
    c._sync()
    assert c.display_name() == "Now the actual question"


def test_a_conversation_is_not_named_after_a_shell_line():
    c = Conversation()
    c.session_id = SESSION
    asyncio.run(
        c.store.append(
            KEY,
            [user_entry("s1", "$ git status\nclean"), user_entry("u1", "What changed?")],
        )
    )
    c._sync()
    assert c.display_name() == "What changed?"


def test_a_conversation_of_nothing_but_commands_stays_unnamed():
    from conftest import command_entry

    c = Conversation()
    c.session_id = SESSION
    asyncio.run(c.store.append(KEY, [command_entry("c1", "/model")]))
    c._sync()
    assert c.display_name() == "New conversation"

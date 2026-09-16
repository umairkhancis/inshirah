"""The durable-object properties: identity, addressing, isolation, durability.

These are what a client needs and the TUI never did. The TUI navigates by
holding object references and serializes turns by grey-ing out its input box;
neither trick survives a process that answers two requests at once.
"""

import asyncio
import json

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import (
    Conversation,
    ConversationBusy,
    ConversationNotFound,
    ConversationRegistry,
    FileStorage,
    MessageNotFound,
)


@pytest.fixture
def tree(key):
    c = Conversation()
    c.session_id = SESSION
    asyncio.run(
        c.store.append(
            key,
            [
                user_entry("u1", "What is an index?"),
                assistant_entry("a1", "An index speeds up lookups."),
                user_entry("u2", "Thanks."),
                assistant_entry("a2", "Any time."),
            ],
        )
    )
    c._sync()
    return c


# --- identity -------------------------------------------------------------


def test_every_thread_has_a_unique_id(tree):
    ids = {t.id for t in [tree, tree.thread_for("a1"), tree.thread_for("a2")]}
    assert len(ids) == 3


def test_a_thread_has_an_id_before_it_has_a_session(tree):
    """A brand new thread is addressable immediately; session_id is still None."""
    thread = tree.thread_for("a1")
    assert thread.id and thread.session_id is None


def test_id_is_stable_when_the_session_is_replaced(tree, monkeypatch):
    """Why id is not session_id: resending the first question replaces it."""

    async def fake_turn(self, prompt):
        self.session_id = "a-completely-new-session"
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    before = tree.id
    asyncio.run(tree.edit_and_resend("u1", "A different question."))

    assert tree.session_id != SESSION  # the provider's id moved
    assert tree.id == before  # the address a client holds did not


# --- addressing -----------------------------------------------------------


def test_a_thread_resolves_by_id_from_anywhere_in_the_tree(tree):
    deep = tree.thread_for("a1").thread_for("x").thread_for("y")
    assert tree.thread(deep.id) is deep
    assert deep.thread(tree.id) is tree  # and back up from a leaf


def test_an_unknown_thread_id_is_reported(tree):
    with pytest.raises(MessageNotFound):
        tree.thread("no-such-thread")


def test_registry_hands_back_the_same_live_object(tree):
    registry = ConversationRegistry()
    created = registry.create()
    assert registry.get(created.id) is created


def test_registry_resolves_a_tree_and_thread_address(tree):
    registry = ConversationRegistry()
    root = registry.create()
    thread = root.thread_for("a1")
    assert registry.thread(root.id, thread.id) is thread
    assert registry.thread(root.id) is root  # no thread id means the root


def test_registry_reports_an_unknown_conversation():
    with pytest.raises(ConversationNotFound):
        ConversationRegistry().get("no-such-conversation")


# --- isolation ------------------------------------------------------------


def test_concurrent_turns_do_not_interleave(tree, monkeypatch):
    """The whole tree serializes: a second send waits, it does not overlap."""
    live, overlapped = 0, []

    async def fake_turn(self, prompt):
        nonlocal live
        live += 1
        overlapped.append(live > 1)
        await asyncio.sleep(0.01)  # a turn is slow; the window is real
        live -= 1
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)

    async def both():
        await asyncio.gather(tree.send("one"), tree.send("two"))

    asyncio.run(both())
    assert overlapped == [False, False]


def test_a_thread_waits_on_a_turn_running_in_its_parent(tree, monkeypatch):
    """One transcript, one lock — the tree is the boundary, not the thread."""
    order = []

    async def fake_turn(self, prompt):
        order.append(f"start {prompt}")
        await asyncio.sleep(0.01)
        order.append(f"end {prompt}")
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    thread = tree.thread_for("a1")

    async def both():
        await asyncio.gather(tree.send("parent"), thread.send("child"))

    asyncio.run(both())
    assert order == ["start parent", "end parent", "start child", "end child"]


def test_editing_during_a_turn_is_refused(tree, monkeypatch):
    """An edit cannot wait for the lock, so it is rejected rather than queued."""
    refused = []

    async def fake_turn(self, prompt):
        try:
            tree.edit("a1", "rewritten mid-flight")
        except ConversationBusy:
            refused.append(True)
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(tree.send("hello"))

    assert refused == [True]
    assert tree.turns[1].text == "An index speeds up lookups."  # untouched


def test_branching_during_a_turn_is_allowed(tree, monkeypatch):
    """Branching reads, never writes — no reason to refuse it."""

    async def fake_turn(self, prompt):
        tree.thread_for("a1")
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(tree.send("hello"))
    assert "a1" in tree.threads


# --- durability -----------------------------------------------------------


def test_dump_is_json(tree):
    tree.thread_for("a1")
    json.dumps(tree.dump())  # raises if anything in there is not serializable


def test_restore_brings_back_the_conversation(tree):
    restored = Conversation.restore(tree.dump())
    assert [(t.role, t.text) for t in restored.turns] == [
        ("user", "What is an index?"),
        ("assistant", "An index speeds up lookups."),
        ("user", "Thanks."),
        ("assistant", "Any time."),
    ]


def test_restore_keeps_every_id_so_saved_links_still_resolve(tree):
    thread = tree.thread_for("a1")
    nested = thread.thread_for("x")
    restored = Conversation.restore(tree.dump())

    assert restored.id == tree.id
    assert restored.thread(thread.id).branch_point == "a1"
    assert restored.thread(nested.id).depth == 2


def test_restore_keeps_what_a_thread_inherited(tree):
    thread = tree.thread_for("a1")
    assert thread.inherited == 2
    restored = Conversation.restore(tree.dump())
    assert restored.thread(thread.id).inherited == 2


def test_restore_keeps_the_session_the_model_resumes(tree):
    assert Conversation.restore(tree.dump()).session_id == SESSION


def test_a_restored_tree_is_one_object_again(tree):
    """Threads must share the rebuilt transcript, not get copies of it."""
    restored = Conversation.restore(tree.dump())
    thread = restored.thread_for("a1")
    assert thread.store is restored.store


def test_file_storage_survives_a_new_registry(tmp_path, tree):
    """The actual durability claim: a restart does not lose the conversation."""
    storage = FileStorage(tmp_path / "conversations")
    first = ConversationRegistry(storage)
    first._live[tree.id] = tree
    first.save(tree)

    second = ConversationRegistry(FileStorage(tmp_path / "conversations"))
    recovered = second.get(tree.id)

    assert recovered is not tree  # genuinely rebuilt, not the same object
    assert [t.text for t in recovered.turns] == [t.text for t in tree.turns]
    assert second.ids() == [tree.id]


def test_deleting_a_conversation_removes_it_from_storage(tmp_path, tree):
    registry = ConversationRegistry(FileStorage(tmp_path / "conversations"))
    registry._live[tree.id] = tree
    registry.save(tree)
    registry.delete(tree.id)

    assert registry.ids() == []
    with pytest.raises(ConversationNotFound):
        registry.get(tree.id)

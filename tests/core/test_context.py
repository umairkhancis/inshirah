"""What the model sees.

``load()`` is the whole contract: whatever it returns is materialized and handed
to the model verbatim. Every test here asserts on that list, because the bugs
this suite protects against were all "the transcript said one thing, the model
was given another".
"""

import asyncio

from conftest import SESSION, assistant_entry, context_of, user_entry
from inshirah.core.store import TranscriptStore


def test_plain_conversation_is_passed_through(store, key):
    assert context_of(store, key) == [
        ("user", "Invent a codename."),
        ("assistant", "Falcon"),
        ("user", "Recap please."),
        ("assistant", "The codename is Falcon."),
    ]


def test_edit_replaces_the_text_the_model_sees(store, key):
    store.edit(SESSION, "a2", "The codename is Petra.")
    assert context_of(store, key)[-1] == ("assistant", "The codename is Petra.")


def test_edit_removes_the_original_entirely(store, key):
    store.edit(SESSION, "a2", "The codename is Petra.")
    assert "Falcon" not in "".join(t for _, t in context_of(store, key)[2:])


def test_edit_truncates_everything_after_it(store, key):
    """The C=30/D=40 regression: a stale copy downstream contradicts the edit."""
    dropped = store.edit(SESSION, "a1", "Petra")
    assert dropped == 3  # noise line, the follow-up question, and its reply
    assert context_of(store, key) == [
        ("user", "Invent a codename."),
        ("assistant", "Petra"),
    ]


def test_editing_at_origin_leaves_no_stale_copy(store, key):
    store.edit(SESSION, "a1", "Petra")
    assert not any("Falcon" in text for _, text in context_of(store, key))


def test_editing_a_user_turn_keeps_string_content(store, key):
    """User content is a bare string; assistant content is a block list."""
    store.edit(SESSION, "u1", "Invent a planet name.")
    entries = asyncio.run(store.load(key))
    assert entries[0]["message"]["content"] == "Invent a planet name."


def test_editing_an_assistant_turn_keeps_block_list(store, key):
    store.edit(SESSION, "a1", "Petra")
    entries = asyncio.run(store.load(key))
    assert entries[1]["message"]["content"] == [{"type": "text", "text": "Petra"}]


def test_edit_does_not_change_the_session(store, key):
    """An in-place edit must not fork — same session id, no duplicate history."""
    before = asyncio.run(store.load(key))[0]["sessionId"]
    store.edit(SESSION, "a2", "Petra")
    after = asyncio.run(store.load(key))[0]["sessionId"]
    assert before == after == SESSION


def test_unknown_uuid_is_reported_and_changes_nothing(store, key):
    before = context_of(store, key)
    assert store.edit(SESSION, "does-not-exist", "Petra") == -1
    assert context_of(store, key) == before


def test_unknown_session_is_reported(store):
    assert store.edit("no-such-session", "a1", "Petra") == -1


def test_messages_skips_non_message_and_empty_entries(store, key):
    asyncio.run(store.append(key, [assistant_entry("a3", "")]))
    uuids = [e["uuid"] for e in store.messages(SESSION)]
    assert uuids == ["u1", "a1", "u2", "a2"]  # no "n1" queue line, no empty "a3"


def test_sessions_are_isolated_from_each_other(store):
    other = {"project_key": "proj", "session_id": "99999999-0000-0000-0000-000000000000"}
    asyncio.run(store.append(other, [user_entry("x1", "different conversation")]))
    store.edit(SESSION, "a2", "Petra")
    assert context_of(store, other) == [("user", "different conversation")]


def test_load_returns_none_for_unknown_session():
    empty = TranscriptStore()
    assert asyncio.run(empty.load({"project_key": "p", "session_id": "nope"})) is None


def test_subagent_transcripts_are_stored_separately(store, key):
    sub = {**key, "subpath": "subagents/agent-1"}
    asyncio.run(store.append(sub, [user_entry("s1", "subagent work")]))
    assert context_of(store, sub) == [("user", "subagent work")]
    assert len(context_of(store, key)) == 4


def test_truncate_removes_the_message_and_everything_after(store, key):
    """Unlike edit, truncate drops the message too — so it can be sent again."""
    dropped = store.truncate(SESSION, "u2")
    assert dropped == 2
    assert context_of(store, key) == [
        ("user", "Invent a codename."),
        ("assistant", "Falcon"),
    ]


def test_truncate_reports_an_unknown_message(store):
    assert store.truncate(SESSION, "does-not-exist") == -1


def test_truncating_the_first_message_empties_the_conversation(store, key):
    store.truncate(SESSION, "u1")
    assert context_of(store, key) == []

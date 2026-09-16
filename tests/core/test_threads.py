"""Threading behaviour: what a thread is given, and what it must not leak.

A thread sees the conversation up to the message it hangs off — not what came
after it in the parent, and never its own messages in the parent's context.
"""

import asyncio

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import Conversation

THREAD_SESSION = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"


@pytest.fixture
def root(key):
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


def test_thread_is_created_once_per_message(root):
    assert root.thread_for("a1") is root.thread_for("a1")


def test_threads_on_different_messages_are_separate(root):
    assert root.thread_for("a1") is not root.thread_for("a2")


def test_thread_starts_empty_and_one_level_deeper(root):
    thread = root.thread_for("a1")
    assert thread.turns == []
    assert thread.depth == 1 and root.depth == 0


def test_threads_nest_to_any_depth(root):
    deep = root.thread_for("a1").thread_for("x").thread_for("y")
    assert deep.depth == 3


def test_first_message_in_a_thread_branches_the_parent(root):
    """resume_session_at slices the parent at the branch point; fork keeps it intact."""
    options = root.thread_for("a1")._options()
    assert options.resume == SESSION  # the parent's session
    assert options.resume_session_at == "a1"  # sliced here — a2 is excluded
    assert options.fork_session is True  # parent is left untouched


def test_later_messages_continue_the_thread_itself(root):
    thread = root.thread_for("a1")
    thread.session_id = THREAD_SESSION
    options = thread._options()

    assert options.resume == THREAD_SESSION
    assert options.resume_session_at is None  # only the first message branches
    assert options.fork_session is False


def test_main_conversation_never_branches(root):
    options = root._options()
    assert options.resume_session_at is None and options.fork_session is False


def test_thread_messages_stay_out_of_the_parent(root, key):
    """The parent's context is untouched by anything said in a thread."""
    thread = root.thread_for("a1")
    thread.session_id = THREAD_SESSION
    asyncio.run(
        thread.store.append(
            {"project_key": "proj", "session_id": THREAD_SESSION},
            [user_entry("t1", "What about b-trees?")],
        )
    )
    thread._sync()

    assert [t.text for t in thread.turns] == ["What about b-trees?"]
    assert "b-trees" not in " ".join(t.text for t in root.turns)


def test_threads_share_one_store(root):
    assert root.thread_for("a1").store is root.store


def test_reply_count_counts_replies_not_inherited_context(root, key):
    """A fork copies the parent in, so counting ``turns`` would overcount."""
    assert root.reply_count("a1") == 0
    forked(root, key)  # inherits 2, then says 2 of its own
    assert root.reply_count("a1") == 2


def test_reply_count_is_zero_for_a_message_with_no_thread(root):
    assert root.reply_count("a2") == 0


def test_failed_turn_is_rolled_back_out_of_the_context(root, key):
    """An API error must not survive as an assistant message in the context."""
    asyncio.run(root.store.append(key, [assistant_entry("e1", "API Error: flagged")]))
    root.store.rollback(SESSION, 4)
    root._sync()
    assert "API Error" not in " ".join(t.text for t in root.turns)
    assert len(root.turns) == 4


# --- what a reader sees, as opposed to what the model is sent ------------


def forked(root, key) -> Conversation:
    """A thread after its first turn.

    The fork slices the parent at the branch point and gives the thread its own
    session, so the thread's transcript legitimately *begins* with the parent's
    history — that is what ``own_turns`` exists to hide from the reader.
    """
    thread = root.thread_for("a1")
    thread.session_id = THREAD_SESSION
    asyncio.run(
        thread.store.append(
            {"project_key": "proj", "session_id": THREAD_SESSION},
            [
                user_entry("u1", "What is an index?"),  # inherited by the fork
                assistant_entry("a1", "An index speeds up lookups."),  # inherited
                user_entry("t1", "Why not a hash?"),  # said in the thread
                assistant_entry("t2", "Ranges."),  # said in the thread
            ],
        )
    )
    thread._sync()
    return thread


def test_a_thread_does_not_re_show_the_conversation_it_branched_from(root, key):
    """The reported bug: after the first reply the whole parent reappeared."""
    thread = forked(root, key)
    assert [t.text for t in thread.own_turns] == ["Why not a hash?", "Ranges."]


def test_the_inherited_messages_are_still_in_the_context(root, key):
    """Hidden from the reader, never withheld from the model."""
    thread = forked(root, key)
    assert "What is an index?" in [t.text for t in thread.turns]
    assert len(thread.turns) == 4 and len(thread.own_turns) == 2


def test_an_unstarted_thread_has_nothing_of_its_own(root):
    assert root.thread_for("a1").own_turns == []


def test_the_main_conversation_owns_everything_it_holds(root):
    """It inherits nothing, so a client can render own_turns without a special case."""
    assert root.own_turns == root.turns


# --- editing the parent after a thread has branched off it ---------------


def test_a_started_thread_shows_the_message_it_actually_forked(root, key):
    """Reported: editing the main conversation changed the thread's first message.

    The fork captured the wording at branch time and the thread's model has
    never been told otherwise, so showing the parent's new wording would put a
    message on screen that is in nobody's context.
    """
    thread = forked(root, key)
    root.edit("a1", "An index is a sorted copy. REWRITTEN.")

    assert thread.branch_turn.text == "An index speeds up lookups."
    assert "REWRITTEN" not in " ".join(t.text for t in thread.turns)


def test_an_unstarted_thread_shows_the_parents_current_wording(root):
    """Nothing has been forked yet, so the parent's copy is the one it will get."""
    thread = root.thread_for("a1")
    root.edit("a1", "Rewritten before the thread ever ran.")
    assert thread.branch_turn.text == "Rewritten before the thread ever ran."


def test_a_started_thread_keeps_its_name_when_the_parent_discards_it(root, key):
    """Editing earlier truncates the branch point away; the thread still knows
    what it hangs off, because it kept a copy."""
    thread = forked(root, key)
    root.edit("u1", "Something else entirely")  # drops a1, u2, a2

    assert "u1" not in [t.uuid for t in root.turns[1:]]
    assert thread.title() == "What is an index?"
    assert thread.branch_turn is not None


def test_an_empty_thread_whose_branch_point_is_gone_is_dropped(root):
    """It could only resume the parent at a message the transcript no longer has."""
    root.thread_for("a2")
    assert "a2" in root.threads
    root.edit("u1", "Something else entirely")  # discards a1, u2, a2
    assert root.threads == {}


def test_a_thread_holding_work_is_never_dropped_by_an_edit(root, key):
    """Its session stands on its own; discarding it would destroy real work."""
    thread = forked(root, key)
    root.edit("u1", "Something else entirely")

    assert root.threads.get("a1") is thread
    assert [t.text for t in thread.own_turns] == ["Why not a hash?", "Ranges."]


def test_threads_left_hanging_are_reportable(root, key):
    """Kept, but nothing in the transcript points at them — a client has to say so."""
    thread = forked(root, key)
    assert root.orphaned_threads() == []
    root.edit("u1", "Something else entirely")
    assert root.orphaned_threads() == [thread]


def test_an_edit_that_keeps_the_branch_point_leaves_the_thread_attached(root, key):
    """Rewriting the branched-from message itself must not orphan its thread."""
    thread = forked(root, key)
    root.edit("a1", "Rewritten in place")
    assert root.threads.get("a1") is thread
    assert root.orphaned_threads() == []
    assert root.reply_count("a1") == 2

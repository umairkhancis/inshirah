"""The counters.

A counter nobody checks is worse than no counter, because it gets believed.
These are the checks: that the numbers go up when the thing they name happens,
that they survive a file nobody should have been editing, and that a session
which ended badly still lands in the histogram.
"""

import asyncio
import json

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import Conversation, usage


@pytest.fixture
def convo(key):
    c = Conversation()
    c.session_id = SESSION
    asyncio.run(
        c.store.append(
            key,
            [
                user_entry("u1", "Invent a codename."),
                assistant_entry("a1", "Falcon"),
                user_entry("u2", "Recap please."),
                assistant_entry("a2", "The codename is Falcon."),
            ],
        )
    )
    c._sync()
    return c


# --- counting --------------------------------------------------------------


def test_nothing_is_written_until_something_happens():
    assert not usage.path().exists()


def test_a_count_creates_the_file_and_its_parent():
    usage.record("threads")
    assert usage.load()["totals"]["threads"] == 1


def test_counts_accumulate_across_processes():
    """Each call is a read-modify-write, so a second process picks up the first
    one's total rather than starting from whatever it had in memory."""
    usage.record("turns")
    usage.record("turns")
    usage.record("turns")
    assert usage.load()["totals"]["turns"] == 3


def test_an_unknown_event_is_ignored_rather_than_stored():
    """The payload is derived from ``TOTALS``; a typo must not become a field."""
    usage.record("prompts")
    assert "prompts" not in usage.load()["totals"]


def test_an_edit_is_attributed_to_whose_message_it_was():
    usage.record_edit("assistant")
    usage.record_edit("user")
    usage.record_edit("user")
    totals = usage.load()["totals"]
    assert totals["edits"] == 3
    assert totals["edits_assistant"] == 1
    assert totals["edits_user"] == 2


# --- the switch and the failure modes --------------------------------------


def test_the_env_var_stops_it_writing_at_all(monkeypatch):
    monkeypatch.setenv(usage.DISABLE, "1")
    usage.record("edits")
    usage.start_session()
    assert not usage.path().exists()


def test_an_unreadable_file_loses_counts_and_raises_nothing():
    usage.record("edits")
    usage.path().write_text("{ this is not json")
    assert usage.load()["totals"]["edits"] == 0
    usage.record("edits")  # and the next write repairs it
    assert usage.load()["totals"]["edits"] == 1


def test_a_file_from_a_future_version_is_not_half_believed():
    usage.path().parent.mkdir(parents=True, exist_ok=True)
    usage.path().write_text(json.dumps({"version": 99, "totals": {"edits": 400}}))
    assert usage.load()["totals"]["edits"] == 0


def test_a_hand_edited_value_of_the_wrong_type_is_dropped():
    usage.path().parent.mkdir(parents=True, exist_ok=True)
    usage.path().write_text(
        json.dumps({"version": usage.VERSION, "totals": {"edits": "lots"}})
    )
    assert usage.load()["totals"]["edits"] == 0


def test_an_unwritable_directory_does_not_break_the_app(monkeypatch, tmp_path):
    """A counter is a side effect of doing the work. It may never be the reason
    an edit fails."""
    monkeypatch.setattr(usage, "DIRECTORY", tmp_path / "nope" / "deeper")
    monkeypatch.setattr(
        usage.pathlib.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    usage.record("edits")  # no exception


# --- sessions --------------------------------------------------------------


def test_the_first_session_does_not_invent_a_previous_one():
    usage.start_session()
    assert usage.load()["edited_sessions"] == {}
    assert usage.load()["totals"]["sessions"] == 1


def test_a_session_is_bucketed_by_how_much_editing_happened_in_it():
    usage.start_session()
    usage.record_edit("assistant")
    usage.record_edit("assistant")
    usage.start_session()  # the second run folds the first one in
    assert usage.load()["edited_sessions"] == {"2": 1}


def test_a_session_with_no_edits_still_counts_in_the_denominator():
    usage.start_session()
    usage.start_session()
    assert usage.load()["edited_sessions"] == {"0": 1}


def test_a_heavily_edited_session_lands_in_the_open_bucket():
    usage.start_session()
    for _ in range(9):
        usage.record_edit("assistant")
    usage.start_session()
    assert usage.load()["edited_sessions"] == {"3+": 1}


def test_the_session_in_progress_is_reported_without_being_written():
    """--stats is usually run from inside the sitting it is describing."""
    usage.start_session()
    usage.record_edit("assistant")
    usage.record_edit("assistant")
    assert usage.summary()["sessions_2plus_edits"] == 1
    assert usage.load()["edited_sessions"] == {}  # still unfolded on disk


def test_a_killed_session_is_folded_in_by_the_next_run():
    """Nothing runs on the way out — the window is closed, the process is
    killed — so the fold has to happen on the way in."""
    usage.start_session()
    usage.record_edit("user")
    # no graceful exit of any kind here
    usage.start_session()
    assert usage.load()["edited_sessions"] == {"1": 1}


def test_reset_forgets_everything():
    usage.record("edits")
    usage.reset()
    assert usage.load()["totals"]["edits"] == 0


# --- what the engine counts, without the client asking it to ---------------


def test_editing_a_reply_is_counted_as_an_edit_of_the_model(convo):
    convo.edit("a1", "Petra")
    totals = usage.load()["totals"]
    assert totals["edits"] == 1
    assert totals["edits_assistant"] == 1
    assert totals["edits_user"] == 0


def test_editing_a_question_is_counted_as_an_edit_of_the_user(convo):
    convo.edit("u2", "Recap in one line.")
    assert usage.load()["totals"]["edits_user"] == 1


def test_a_failed_edit_is_not_counted(convo):
    from inshirah.core import MessageNotFound

    with pytest.raises(MessageNotFound):
        convo.edit("nope", "x")
    assert usage.load()["totals"]["edits"] == 0


def test_branching_a_thread_is_counted_once_however_often_it_is_opened(convo):
    convo.thread_for("a1")
    convo.thread_for("a1")
    convo.thread_for("u2")
    assert usage.load()["totals"]["threads"] == 2


def test_starting_a_conversation_is_counted():
    Conversation()
    assert usage.load()["totals"]["conversations"] == 1


def test_rehydrating_a_conversation_is_not_counted(convo):
    """The rail restores every conversation in the project at startup. Counting
    those would make the number mean "conversations times launches"."""
    data = convo.dump()
    usage.reset()
    Conversation.restore(data)
    assert usage.load()["totals"]["conversations"] == 0


def test_a_thread_is_not_counted_as_a_conversation(convo):
    usage.reset()
    convo.thread_for("a1")
    assert usage.load()["totals"]["conversations"] == 0

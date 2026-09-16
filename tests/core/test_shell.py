"""``!command`` — running a command and holding its output for the next message.

The output is deliberately *not* written into the stored transcript. Claude
Code's transcript is a ``parentUuid``-linked chain with a ``last-prompt`` entry
pointing at its leaf, so an entry appended outside that chain is an orphan the
CLI ignores — the model saw nothing when this was tried. Holding the output
instead needs no knowledge of that private format, and makes it editable before
the model has ever read it.
"""

import asyncio
import os

import pytest

from inshirah.core import Conversation, ConversationBusy, Harness, MessageNotFound
from inshirah.core import shell


def run(command, cwd=None, **kw):
    return asyncio.run(shell.run(command, cwd or os.getcwd(), **kw))


# --- running --------------------------------------------------------------


def test_output_is_captured():
    assert run("echo hello").output == "hello"


def test_a_failing_command_is_a_result_not_an_exception():
    """A non-zero exit is often the interesting one — it belongs in the chat."""
    result = run("exit 3")
    assert result.exit_code == 3 and result.failed


def test_stderr_is_captured_too(tmp_path):
    assert "No such file" in run("ls definitely-not-here", str(tmp_path)).output


def test_a_hanging_command_times_out_instead_of_freezing():
    result = run("sleep 5", timeout=0.3)
    assert result.exit_code == 124 and "timed out" in result.output


def test_a_command_runs_in_the_project_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    assert "marker.txt" in run("ls", str(tmp_path)).output


def test_long_output_is_truncated_so_it_cannot_flood_the_context():
    result = run("seq 1 1000")
    assert result.truncated
    assert len(result.output.splitlines()) == shell.MAX_LINES


# --- how it reads in the conversation -------------------------------------


def test_the_message_reads_like_a_terminal():
    assert run("echo hello").as_message() == "$ echo hello\nhello"


def test_a_failure_shows_its_exit_code():
    assert "(exit 3)" in run("exit 3").as_message()


def test_truncation_is_declared_rather_than_silent():
    assert "truncated" in run("seq 1 1000").as_message()


# --- holding, editing, sending --------------------------------------------


@pytest.fixture
def convo(tmp_path):
    return Conversation(harness=Harness(cwd=str(tmp_path)))


def test_running_a_command_holds_its_output(convo):
    turn = asyncio.run(convo.run_shell("echo held"))
    assert convo.pending == ["$ echo held\nheld"]
    assert turn.uuid == "pending:0"


def test_holding_does_not_touch_the_transcript(convo):
    asyncio.run(convo.run_shell("echo held"))
    assert convo.turns == []  # nothing was sent to the model


def test_held_output_can_be_rewritten_before_the_model_sees_it(convo):
    turn = asyncio.run(convo.run_shell("echo noisy"))
    convo.edit_pending(turn.uuid, "$ echo noisy\nthe one line that matters")
    assert convo.pending == ["$ echo noisy\nthe one line that matters"]


def test_held_output_can_be_dropped(convo):
    turn = asyncio.run(convo.run_shell("echo junk"))
    convo.drop_pending(turn.uuid)
    assert convo.pending == []


def test_editing_output_that_is_not_held_is_reported(convo):
    with pytest.raises(MessageNotFound):
        convo.edit_pending("pending:7", "x")


def test_held_output_is_offered_as_turns_for_rendering(convo):
    asyncio.run(convo.run_shell("echo one"))
    asyncio.run(convo.run_shell("echo two"))
    assert [t.uuid for t in convo.pending_turns] == ["pending:0", "pending:1"]


def test_held_output_goes_in_front_of_the_next_prompt(convo, monkeypatch):
    sent = []

    async def fake_turn(self, prompt):
        sent.append(prompt)
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(convo.run_shell("echo context"))
    asyncio.run(convo.send("what does that mean?"))

    assert sent == ["$ echo context\ncontext\n\nwhat does that mean?"]


def test_held_output_is_only_sent_once(convo, monkeypatch):
    sent = []

    async def fake_turn(self, prompt):
        sent.append(prompt)
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(convo.run_shell("echo once"))
    asyncio.run(convo.send("first"))
    asyncio.run(convo.send("second"))

    assert "once" in sent[0] and "once" not in sent[1]
    assert convo.pending == []


def test_a_command_is_refused_while_a_turn_is_running(convo, monkeypatch):
    refused = []

    async def fake_turn(self, prompt):
        try:
            await convo.run_shell("echo nope")
        except ConversationBusy:
            refused.append(True)
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    asyncio.run(convo.send("hello"))
    assert refused == [True]

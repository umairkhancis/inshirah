"""Conversation behaviour that does not need a model.

``send()`` is excluded on purpose — it spawns the CLI. Everything these tests
cover is the part that decides what the model would be given.
"""

import asyncio

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import Conversation, Harness


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


def test_turns_are_derived_from_the_store(convo):
    """The UI must not track history separately — that drift hid a real bug."""
    assert [(t.role, t.text) for t in convo.turns] == [
        ("user", "Invent a codename."),
        ("assistant", "Falcon"),
        ("user", "Recap please."),
        ("assistant", "The codename is Falcon."),
    ]


def test_every_turn_is_addressable_for_editing(convo):
    assert [t.uuid for t in convo.turns] == ["u1", "a1", "u2", "a2"]


def test_editing_the_last_reply_keeps_the_earlier_turns(convo):
    dropped = convo.edit_last_response("The codename is Petra.")
    assert dropped == 0
    assert [t.text for t in convo.turns][-1] == "The codename is Petra."
    assert len(convo.turns) == 4


def test_editing_an_earlier_turn_drops_the_later_ones(convo):
    dropped = convo.edit("a1", "Petra")
    assert dropped == 2
    assert [(t.role, t.text) for t in convo.turns] == [
        ("user", "Invent a codename."),
        ("assistant", "Petra"),
    ]


def test_editing_a_user_turn_is_supported(convo):
    convo.edit("u1", "Invent a planet name.")
    assert convo.turns[0].text == "Invent a planet name."


def test_last_response_is_none_when_user_spoke_last(convo, key):
    asyncio.run(convo.store.append(key, [user_entry("u3", "still there?")]))
    convo._sync()
    assert convo.last_response is None


def test_editing_an_unknown_message_raises(convo):
    with pytest.raises(ValueError):
        convo.edit("does-not-exist", "Petra")


def test_editing_before_any_message_raises():
    with pytest.raises(ValueError):
        Conversation().edit("a1", "Petra")


def test_options_run_the_real_claude_code_harness(tmp_path):
    """Inshirah is a surface, not a second agent.

    This asserted the exact opposite until the harness was turned on: the app
    used to strip Claude Code down to a plain chat. The intent now is that
    nothing underneath is reimplemented — the prompt and the tools are asked for
    by preset rather than named, so they cannot drift as Claude Code changes.
    """
    options = Conversation(harness=Harness(cwd=str(tmp_path)))._options()

    assert options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert options.tools == {"type": "preset", "preset": "claude_code"}
    assert options.setting_sources is None  # user + project + local, and CLAUDE.md
    assert options.cwd == str(tmp_path)  # the real project, so memory loads
    assert options.permission_mode == "auto"


def test_a_thread_runs_under_the_same_harness_as_its_parent(tmp_path):
    """A thread is a different slice of history, not a different agent."""
    root = Conversation(harness=Harness(permission_mode="plan", cwd=str(tmp_path)))
    assert root.thread_for("a1").harness is root.harness


def test_an_unknown_permission_mode_is_refused():
    with pytest.raises(ValueError):
        Harness(permission_mode="yolo")


def test_options_resume_the_same_session_through_our_store():
    c = Conversation()
    c.session_id = SESSION
    options = c._options()

    assert options.resume == SESSION  # in-place edit: never a fork
    assert options.session_store is c.store  # load() is what the model sees


def test_export_shows_the_edited_context(convo, tmp_path):
    convo.edit("a1", "Petra")
    path = convo.export(str(tmp_path))

    body = path.read_text()
    assert (tmp_path / "latest.md").exists()  # stable path for sharing
    assert "## Context sent to the model" in body
    assert "Petra" in body
    assert "Falcon" not in body


def _stub_send(recorder):
    """Stand in for the turn itself.

    Patches ``_run_turn`` rather than ``send``: ``edit_and_resend`` truncates and
    re-asks under one lock, so it calls the inner form. Patching ``send`` would
    leave the real turn — and the CLI subprocess — in the resend path.
    """

    async def fake_send(self, prompt):
        recorder.append(prompt)
        await self.store.append(
            {"project_key": "proj", "session_id": self.session_id or "fresh"},
            [user_entry("n1", prompt), assistant_entry("n2", "a new answer")],
        )
        self.session_id = self.session_id or "fresh"
        self._sync()
        return self.turns[-1]

    return fake_send


def test_editing_a_question_resends_it(convo, monkeypatch):
    """The bug: saving an edited question left the conversation with no reply."""
    sent: list[str] = []
    monkeypatch.setattr(Conversation, "_run_turn", _stub_send(sent))

    asyncio.run(convo.edit_and_resend("u2", "Recap in one line."))

    assert sent == ["Recap in one line."]  # the new wording was actually asked
    assert [(t.role, t.text) for t in convo.turns] == [
        ("user", "Invent a codename."),
        ("assistant", "Falcon"),
        ("user", "Recap in one line."),
        ("assistant", "a new answer"),
    ]


def test_resending_a_question_does_not_duplicate_it(convo, monkeypatch):
    monkeypatch.setattr(Conversation, "_run_turn", _stub_send([]))
    asyncio.run(convo.edit_and_resend("u2", "Recap in one line."))
    assert [t.text for t in convo.turns].count("Recap in one line.") == 1


def test_editing_the_only_question_starts_a_fresh_session(convo, monkeypatch):
    """Nothing visible survives, so resuming the old session would fail."""
    monkeypatch.setattr(Conversation, "_run_turn", _stub_send([]))
    asyncio.run(convo.edit_and_resend("u1", "A different question."))
    assert convo.session_id != SESSION
    assert [(t.role, t.text) for t in convo.turns] == [
        ("user", "A different question."),
        ("assistant", "a new answer"),
    ]


def test_editing_a_reply_does_not_resend(convo):
    """A rewritten answer replaces what was said; there is nothing to re-ask."""
    convo.edit_last_response("The codename is Petra.")
    assert [t.text for t in convo.turns][-1] == "The codename is Petra."
    assert len(convo.turns) == 4

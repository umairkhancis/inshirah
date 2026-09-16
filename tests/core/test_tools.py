"""Editing in place, once the transcript is full of tool calls.

Under the full harness a transcript is mostly tool_use / tool_result pairs, and
the API rejects a history where a tool_use has no matching tool_result. Editing
cuts the transcript at an arbitrary point, so the two features could have
collided. They do not, for two structural reasons that are easy to break by
accident — which is why they are pinned here:

  1. a line that is only a tool_result carries no text, so it is never
     addressable and an edit can never land between a tool_use and its result;
  2. editing an assistant turn replaces its whole content, so any tool_use in it
     leaves with it.
"""

import asyncio

import pytest

from inshirah.core.store import TranscriptStore, summarize_tool, text_of

SESSION = "sess"


def user(uuid: str, text: str) -> dict:
    return {"type": "user", "uuid": uuid, "sessionId": SESSION,
            "message": {"role": "user", "content": text}}


def assistant(uuid: str, text: str) -> dict:
    return {"type": "assistant", "uuid": uuid, "sessionId": SESSION,
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def assistant_using(uuid: str, text: str, tool_id: str, name: str = "Read") -> dict:
    blocks: list[dict] = [{"type": "text", "text": text}] if text else []
    blocks.append({"type": "tool_use", "id": tool_id, "name": name,
                   "input": {"file_path": "x.py"}})
    return {"type": "assistant", "uuid": uuid, "sessionId": SESSION,
            "message": {"role": "assistant", "content": blocks}}


def tool_result(uuid: str, tool_id: str) -> dict:
    return {"type": "user", "uuid": uuid, "sessionId": SESSION,
            "message": {"role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_id,
                                     "content": "file contents"}]}}


@pytest.fixture
def store() -> TranscriptStore:
    s = TranscriptStore()
    asyncio.run(
        s.append(
            {"session_id": SESSION},
            [
                user("u1", "read x.py and summarise"),
                assistant_using("a1", "I'll read it.", "t1"),
                tool_result("r1", "t1"),
                assistant("a2", "It defines three functions."),
                user("u2", "now the tests too"),
                assistant_using("a3", "", "t2", name="Bash"),  # tool call, no text
                tool_result("r2", "t2"),
                assistant("a4", "Tests look fine."),
            ],
        )
    )
    return s


def dangling(store: TranscriptStore) -> set[str]:
    """tool_use ids with no matching tool_result — what the API rejects."""
    uses, results = set(), set()
    for entry in store.entries(SESSION):
        content = entry.get("message", {}).get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "tool_use":
                    uses.add(block["id"])
                if block.get("type") == "tool_result":
                    results.add(block["tool_use_id"])
    return uses - results


# --- visibility -----------------------------------------------------------


def test_a_tool_call_without_text_is_still_shown(store):
    """Regression: the agent looked idle while it was running commands."""
    assert "a3" in [e["uuid"] for e in store.messages(SESSION)]


def test_a_bare_tool_result_is_not_shown(store):
    shown = [e["uuid"] for e in store.messages(SESSION)]
    assert "r1" not in shown and "r2" not in shown


def test_the_shown_transcript_is_the_addressable_one(store):
    assert [e["uuid"] for e in store.messages(SESSION)] == ["u1", "a1", "a2", "u2", "a3", "a4"]


def test_a_tool_call_is_summarized_for_display(store):
    assert summarize_tool({"name": "Bash", "input": {"command": "pytest  -q"}}) == "Bash(pytest -q)"


def test_summary_falls_back_to_the_bare_tool_name():
    assert summarize_tool({"name": "TodoWrite", "input": {}}) == "TodoWrite"


# --- editing never breaks a tool chain ------------------------------------


@pytest.mark.parametrize("uuid", ["u1", "a1", "a2", "u2", "a3", "a4"])
def test_editing_any_addressable_turn_leaves_no_dangling_tool_use(store, uuid):
    store.edit(SESSION, uuid, "REWRITTEN")
    assert dangling(store) == set()


@pytest.mark.parametrize("uuid", ["u1", "u2"])
def test_resending_any_question_leaves_no_dangling_tool_use(store, uuid):
    """truncate() is the edit-and-resend path; questions are what it cuts at."""
    store.truncate(SESSION, uuid)
    assert dangling(store) == set()


def test_editing_a_turn_takes_its_tool_call_with_it(store):
    """The invariant: content is replaced wholesale, not patched."""
    store.edit(SESSION, "a1", "Never mind.")
    assert dangling(store) == set()
    assert not any("t1" in str(e) for e in store.entries(SESSION))


def test_editing_drops_the_tool_results_that_followed(store):
    store.edit(SESSION, "a2", "Actually it defines four.")
    assert [e["uuid"] for e in store.entries(SESSION)] == ["u1", "a1", "r1", "a2"]
    assert text_of(store.entries(SESSION)[-1]) == "Actually it defines four."


def test_a_long_path_keeps_the_filename():
    """Trimming the front: the end of a path is the part you recognise."""
    summary = summarize_tool(
        {"name": "Read", "input": {"file_path": "/private/var/folders/cv/wrshhvks7dl6/T/tmpabc/hello.txt"}}
    )
    assert summary.endswith("hello.txt)")


def test_a_long_command_keeps_the_start():
    """Trimming the end: a command says what it does at the front."""
    summary = summarize_tool(
        {"name": "Bash", "input": {"command": "pytest -q tests/ " + "-x " * 40}}
    )
    assert summary.startswith("Bash(pytest -q tests/")

"""``!command`` in the TUI.

Claude Code's REPL has bash mode; the SDK does not carry it, because the CLI is
driven in stream-json mode and a leading ``!`` arrives as ordinary prompt text.
Worse, the model recognises the convention and answers as though a command had
run — so this has to be intercepted before the prompt is ever sent.
"""

import asyncio

from textual.widgets import TextArea

from inshirah.core import Conversation, Harness
from inshirah.tui.app import InshirahApp


def drive(monkeypatch, tmp_path, *typed: str, edit: str | None = None) -> dict:
    """Type things into the composer; record anything that reached the model."""
    asked: list[str] = []

    async def fake_turn(self, prompt):
        asked.append(prompt)
        return None

    monkeypatch.setattr(Conversation, "_run_turn", fake_turn)
    captured: dict = {}

    async def scenario() -> None:
        app = InshirahApp(Harness(cwd=str(tmp_path)))
        async with app.run_test(size=(140, 40)) as pilot:
            composer = app.main_pane.composer
            for text in typed:
                composer.input.value = text
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                await pilot.pause()
            if edit is not None:
                app.main_pane.select([r for r in app.main_pane.rows if r.uuid][-1])
                await pilot.press("ctrl+e")
                await pilot.pause()
                app.query_one("#editor", TextArea).text = edit
                await pilot.press("ctrl+s")
                await pilot.pause()
                await app.workers.wait_for_complete()
            captured["pending"] = list(app.conversation.pending)
            captured["authors"] = [r.author for r in app.main_pane.rows]
            captured["bodies"] = [r.body_text for r in app.main_pane.rows]

    asyncio.run(scenario())
    captured["asked"] = asked
    return captured


def test_a_bang_command_never_reaches_the_model(monkeypatch, tmp_path):
    """The bug this exists for: the model would otherwise play along."""
    result = drive(monkeypatch, tmp_path, "!echo hello")
    assert result["asked"] == []


def test_a_bang_command_runs_and_holds_its_output(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!echo hello")
    assert result["pending"] == ["$ echo hello\nhello"]


def test_held_output_is_shown_as_a_shell_message(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!echo hello")
    assert result["authors"] == ["shell"]
    assert "hello" in result["bodies"][0]


def test_a_bare_bang_does_nothing(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!", "!   ")
    assert result["pending"] == [] and result["asked"] == []


def test_an_ordinary_message_still_goes_to_the_model(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "what is an index?")
    assert result["asked"] == ["what is an index?"]


def test_output_rides_along_with_the_next_message(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!echo context", "explain that")
    assert result["asked"] == ["$ echo context\ncontext\n\nexplain that"]
    assert result["pending"] == []


def test_output_can_be_edited_before_the_model_ever_sees_it(monkeypatch, tmp_path):
    """The reason for holding it rather than sending it straight through."""
    result = drive(
        monkeypatch, tmp_path, "!echo noisy", edit="$ echo noisy\nthe one line that matters"
    )
    assert result["pending"] == ["$ echo noisy\nthe one line that matters"]


def test_emptying_held_output_drops_it(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!echo junk", edit="   ")
    assert result["pending"] == []


def test_a_failing_command_is_still_worth_keeping(monkeypatch, tmp_path):
    result = drive(monkeypatch, tmp_path, "!exit 3")
    assert "(exit 3)" in result["pending"][0]


def test_a_thread_has_its_own_shell(monkeypatch, tmp_path):
    """The thread column is a conversation, not a reply box: ! works there too."""
    monkeypatch.setattr(Conversation, "_run_turn", lambda self, prompt: None)
    captured: dict = {}

    async def scenario() -> None:
        app = InshirahApp(Harness(cwd=str(tmp_path)))
        async with app.run_test(size=(140, 40)) as pilot:
            app.conversation.turns.append(
                __import__("inshirah.core", fromlist=["Turn"]).Turn("user", "hi", "u1")
            )
            await app.refresh_all()
            row = [r for r in app.main_pane.rows if r.uuid == "u1"][0]
            await app.open_thread_on(app.main_pane, row)
            await pilot.pause()

            app.thread_pane.composer.input.value = "!echo in-thread"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            captured["thread_pending"] = list(app.thread.pending)
            captured["main_pending"] = list(app.conversation.pending)

    asyncio.run(scenario())
    assert captured["thread_pending"] == ["$ echo in-thread\nin-thread"]
    assert captured["main_pending"] == []  # it did not leak into the parent

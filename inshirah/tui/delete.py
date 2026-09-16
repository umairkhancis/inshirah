"""Deleting a conversation.

The rail accumulates: a question you asked once, a false start, three attempts
at the same thing. A list you cannot prune stops being navigation, so the rail
needs a way to throw one away.

It asks first, and it says what is about to go — the count of messages and
threads is the only signal that distinguishes the false start from the week of
work with the same first line. The rest of the app is built on the idea that an
edit is reversible in spirit (the text is still yours to retype); this is not,
so the confirm names the export that is, and the safe button is the one that
starts focused.
"""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def why(summary: dict) -> str:
    """What is about to be lost — the line that tells a false start from a week.

    Two conversations can open with the same question; the counts are what
    distinguish the one worth keeping. An empty one is said plainly rather than
    as "0 messages go with it", which reads like a warning about nothing.
    """
    if not summary["messages"] and not summary["threads"]:
        return "Nothing has been said in this one yet."
    parts = [plural(summary["messages"], "message")]
    if summary["threads"]:
        parts.append(plural(summary["threads"], "thread"))
    return (
        f"{' and '.join(parts)} go with it, and nothing brings them back. "
        "Escape here, then ctrl+x, writes the conversation to markdown first."
    )


class DeleteConversation(ModalScreen[bool]):
    """Dismisses True to delete it, False to keep it."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, summary: dict) -> None:
        super().__init__()
        self.summary = summary

    def compose(self) -> ComposeResult:
        with Vertical(id="box", classes="panel"):
            yield Label("Delete this conversation?", classes="panel-title")
            # Text(), not a string: the name is the user's own words, and a
            # conversation that opened with "[link] is broken" must not be read
            # as markup here of all places.
            yield Static(Text(self.summary["name"]), id="subject")
            yield Static(why(self.summary), id="why")
            with Horizontal(id="choices"):
                yield Button("Delete", variant="error", id="delete")
                yield Button("Keep it", id="cancel")

    def on_mount(self) -> None:
        # The safe one is where the return key already is.
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "delete")

    def action_cancel(self) -> None:
        self.dismiss(False)

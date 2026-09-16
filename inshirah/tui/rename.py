"""Naming a conversation.

A conversation names itself after the first thing you asked it, which is right
almost always and wrong exactly when the conversation turned into something
else. This is the escape hatch; clearing the field goes back to the derived
name rather than leaving it blank.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class RenameConversation(ModalScreen[str | None]):
    """Returns the new name, "" to go back to the derived one, or None if cancelled."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, current: str) -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="box", classes="panel"):
            yield Label("Name this conversation", classes="panel-title")
            yield Input(value=self.current, id="name")
            yield Static(
                "Leave it empty to go back to naming it after the first message.",
                id="why",
            )
            with Horizontal(id="choices"):
                yield Button("Save", variant="success", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def _save(self) -> None:
        self.dismiss(self.query_one("#name", Input).value)

    def on_input_submitted(self) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one("#name", Input).value if event.button.id == "save" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)

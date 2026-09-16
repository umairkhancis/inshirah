"""The permission prompt — Inshirah's stand-in for Claude Code's own.

Claude Code asks before it runs a command or rewrites a file. Under the full
harness Inshirah has to ask the same question, because the SDK has nowhere to
send an "ask" decision otherwise: with no ``can_use_tool`` callback it raises
``canUseTool callback is not provided`` in the middle of a turn.

Only calls the CLI could not settle on its own arrive here. Anything already
covered by ``permissions.allow`` in settings.json, by ``--allow``, or by a mode
like ``acceptEdits`` never reaches this screen.
"""

from typing import Any

from claude_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from inshirah.core import summarize_tool


class PermissionRequest(ModalScreen[bool]):
    """Ask whether one tool call may run. Returns True to allow."""

    BINDINGS = [("escape", "deny", "Deny")]

    def __init__(self, tool: str, arguments: dict[str, Any]) -> None:
        super().__init__()
        self.tool = tool
        self.arguments = arguments

    def compose(self) -> ComposeResult:
        with Vertical(id="box", classes="panel"):
            yield Label(f"{self.tool} wants to run", classes="panel-title")
            # What would actually happen, not just which tool asked — a name
            # alone is not enough to decide on.
            yield Static(
                summarize_tool({"name": self.tool, "input": self.arguments}), id="detail"
            )
            yield Static(
                "Only calls Claude Code could not settle from your settings "
                "reach here. Denying tells the model why, so it can try "
                "something else.",
                id="why",
            )
            with Horizontal(id="choices"):
                yield Button("Allow", variant="success", id="allow")
                yield Button("Deny", variant="error", id="deny")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "allow")

    def action_deny(self) -> None:
        self.dismiss(False)


def handler(app: Any):
    """A ``can_use_tool`` callback that asks through ``app``.

    Runs inside the send worker, so it can wait on a screen without blocking
    the UI — which is why sending is a worker in the first place.
    """

    async def can_use_tool(
        tool: str, arguments: dict[str, Any], context: ToolPermissionContext
    ):
        allowed = await app.push_screen_wait(PermissionRequest(tool, arguments))
        if allowed:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"{tool} denied by the user")

    return can_use_tool

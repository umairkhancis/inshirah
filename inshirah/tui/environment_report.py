"""What Claude Code loaded in this project, on screen.

Everything here is resolved by Claude Code itself — the project's CLAUDE.md and
memory, ``.claude/skills``, ``.claude/agents``, hooks from
``.claude/settings.json``, ``.mcp.json`` servers, plugins. None of it is
Inshirah's, which is the point: this screen exists so you can see that working
in a directory here loads the same things working in it under ``claude`` would.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from inshirah.core import Environment


class EnvironmentReport(ModalScreen[None]):
    """A read-only dump of the resolved project configuration."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+i", "close", "Close", priority=True),
    ]

    def __init__(self, environment: Environment) -> None:
        super().__init__()
        self.environment = environment

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="report", classes="panel"):
            yield Static("what this project loaded", classes="panel-title")
            yield Static(self.environment.report(), id="body")

    def action_close(self) -> None:
        self.dismiss(None)

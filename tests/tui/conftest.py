"""Fixtures for the TUI tests.

The app asks the CLI what slash commands this project has as soon as it starts.
That is free in tokens but it spawns the real `claude` process, which a test
suite must never do — it is slow, it needs credentials, and the subprocess
outlives the test's event loop. Every TUI test gets a fixed list instead, so the
menu is testable and nothing reaches the network.
"""

import pytest

from inshirah.core import SlashCommand
from inshirah.tui import app as app_module

# Re-exported: this file shadows tests/conftest.py for ``from conftest import``
# inside tests/tui, and the transcript builders are shared.
from tests.conftest import (  # noqa: F401
    SESSION,
    assistant_entry,
    command_entry,
    command_output_entry,
    meta_entry,
    user_entry,
)

COMMANDS = (
    SlashCommand("clear", "Start a new session with empty context", "[name]"),
    SlashCommand("compact", "Free up context by summarizing the conversation", ""),
    SlashCommand("context", "Show current context usage", ""),
    SlashCommand("init", "Initialize a new CLAUDE.md file", ""),
    SlashCommand("rename", "Rename the current conversation", "[name]"),
    SlashCommand("review", "Review the current diff", "[target]"),
    SlashCommand("zorblat", "Report the zorblat code (project)", "<component>"),
)


@pytest.fixture(autouse=True)
def offline_commands(monkeypatch):
    """No test may start the real CLI to find out what commands exist."""

    async def fixed(harness):
        return COMMANDS

    monkeypatch.setattr(app_module, "load_commands", fixed)
    return COMMANDS

"""The engine's public surface — the only names a client should import.

A client (the TUI today, a web app next) builds on these and nothing else. The
submodules stay importable for tests and for monkeypatching module globals, but
a client reaching past this file is a sign the seam is in the wrong place.

A conversation tree is a durable object:

    identity     ``Conversation.id`` — assigned once, never reused, and safe in
                 a URL. Not ``session_id``, which is None until the first
                 message lands and which the provider may replace.
    addressing   ``ConversationRegistry.thread(tree_id, thread_id)`` turns an id
                 back into the live object, rehydrating it if it was evicted.
    isolation    turns are serialized per tree, so two requests cannot interleave
                 in one shared transcript. Mutations that cannot wait raise
                 ``ConversationBusy``.
    durability   ``dump()``/``restore()`` round-trip the whole tree as JSON;
                 ``FileStorage`` persists it.

The tree, not the individual thread, is that object — threads share a transcript
and a thread's first message resumes its parent's session, so the tree is the
smallest internally consistent unit.

Reads go through ``snapshot()`` / ``tree_snapshot()``, which return plain JSON
including the ids the write calls take back. ``render_export()`` returns the
export as markdown; ``export()`` is the wrapper that writes it to a file.

How much of Claude Code is running is ``Harness``: by default the real agent
preset, the whole tool suite, and the settings and CLAUDE.md of the directory
you launched in. Inshirah is the surface; nothing underneath is reimplemented.
A client that runs any permission mode which can prompt must pass
``can_use_tool`` — the SDK raises mid-turn without one.

``Conversation.environment`` is what Claude Code resolved in the project
directory — skills, agents, MCP servers, memory paths — as the CLI reported it.
None of that is reimplemented here; the value of reporting it is that a skill
that failed to parse or an MCP server that died looks exactly like one that
works. ``probe`` asks the same question without a conversation.

``run_shell`` is ``!command``: it runs the command and holds the output for the
next prompt rather than writing it into the transcript, because Claude Code's
transcript is a parentUuid-linked chain and an entry outside that chain is
ignored. Holding it is also what makes the output editable before the model
reads it — see ``pending_turns`` / ``edit_pending`` / ``drop_pending``.

``usage`` counts what was used — sessions, edits, threads — into a file in the
user's home directory. A client instruments nothing itself: the counters live on
the engine's own methods, so a second front end gets them without knowing they
exist. The one thing a client must do is call ``usage.start_session()`` when it
starts, because only a client knows what a session is.

Still open before a web app feels right: ``send()`` runs a turn to completion
and returns, so there is no token streaming yet.
"""

from . import usage
from .commands import SlashCommand, load as load_commands, split as split_command
from .config import PROVIDER, PROVIDER_NAME, PROVIDERS, Provider
from .conversation import Conversation, Turn
from .environment import Environment, probe
from .harness import CLAUDE_CODE, PERMISSION_MODES, Harness
from .privacy import report as privacy_report
from .setup import claude_binary, explain as explain_setup_failure
from .shell import ShellResult
from .errors import (
    ConversationBusy,
    ConversationNotFound,
    InshirahError,
    MessageNotFound,
    NothingToEdit,
    SendFailed,
)
from .registry import (
    ConversationRegistry,
    FileStorage,
    MemoryStorage,
    Storage,
)
from .store import TranscriptStore, summarize_tool, text_of, tool_calls_of

__all__ = [
    # conversation
    "Conversation",
    "Turn",
    # how much of Claude Code is switched on
    "Harness",
    "CLAUDE_CODE",
    "PERMISSION_MODES",
    # what the project loaded
    "Environment",
    "probe",
    # `!command`
    "ShellResult",
    # first-run failures, said usefully
    "explain_setup_failure",
    "claude_binary",
    # the claim that there is no backend, printed from the code
    "privacy_report",
    # what this copy has been used for, counted on this machine
    "usage",
    # slash commands, as the CLI reports them
    "SlashCommand",
    "load_commands",
    "split_command",
    # addressing and durability
    "ConversationRegistry",
    "Storage",
    "MemoryStorage",
    "FileStorage",
    # transcript
    "TranscriptStore",
    "text_of",
    "tool_calls_of",
    "summarize_tool",
    # errors
    "InshirahError",
    "SendFailed",
    "ConversationBusy",
    "ConversationNotFound",
    "MessageNotFound",
    "NothingToEdit",
    # configuration
    "Provider",
    "PROVIDER",
    "PROVIDER_NAME",
    "PROVIDERS",
]

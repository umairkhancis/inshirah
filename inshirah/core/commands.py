"""The slash commands this project has, as Claude Code reports them.

None of this is reimplemented. The CLI already resolves every command a
directory offers — its own built-ins, ``.claude/commands`` in the project,
``~/.claude/commands``, plugin and skill commands — and hands back the list on
connect. Inshirah asks for that list so it can *offer* the commands, and then
sends whatever you typed through untouched so the CLI executes it exactly as it
would in ``claude``.

That matters for arguments especially. ``$ARGUMENTS``, ``$1``, ``!`` blocks and
``@file`` references inside a command's markdown are expanded by the CLI, not
here; expanding them again would be a second implementation to drift from the
first, and the quirks would differ from what the same command does under
``claude``.

Two commands are the exception, and only because they are about the *surface*
rather than the agent — see ``inshirah.tui.app``. The CLI's ``/clear`` starts a
fresh session and leaves the old one behind, which is precisely what a new
conversation is here; its ``/rename`` renames a conversation this app draws
itself.
"""

from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from .harness import Harness

# Commands the CLI carries for its own plumbing rather than for a person to run.
HIDDEN_PREFIX = "__"

# Handled by the client, because they act on the surface and not on the agent.
LOCAL = ("clear", "rename")


@dataclass(frozen=True)
class SlashCommand:
    """One command the CLI says this project offers."""

    name: str
    description: str = ""
    argument_hint: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def takes_arguments(self) -> bool:
        return bool(self.argument_hint)

    @property
    def source(self) -> str:
        """``project``/``user`` when the CLI says so, else "".

        The CLI marks where a custom command came from by appending it to the
        description. Anything unmarked is one of its own, so this reports what
        was said rather than guessing a taxonomy.
        """
        tail = self.description.rsplit("(", 1)[-1].rstrip()
        if self.description.endswith(")") and tail.rstrip(")") in ("project", "user"):
            return tail.rstrip(")")
        return ""

    @property
    def summary(self) -> str:
        """The description without the trailing source marker."""
        if self.source:
            return self.description.rsplit("(", 1)[0].strip()
        return self.description

    @property
    def local(self) -> bool:
        return self.name in LOCAL

    def matches(self, typed: str) -> bool:
        """Does what has been typed so far pick this command out?"""
        typed = typed.lstrip("/").lower()
        if not typed:
            return True
        return any(typed in name.lower() for name in (self.name, *self.aliases))


def parse(payload: Any) -> tuple[SlashCommand, ...]:
    """Turn the CLI's command list into ours, dropping its internal plumbing."""
    found = []
    for entry in payload or ():
        if not isinstance(entry, dict):
            found.append(SlashCommand(name=str(entry)))
            continue
        name = entry.get("name") or ""
        if not name or name.startswith(HIDDEN_PREFIX):
            continue
        aliases = entry.get("aliases") or ()
        found.append(
            SlashCommand(
                name=name,
                description=entry.get("description") or "",
                argument_hint=entry.get("argumentHint") or "",
                aliases=tuple(str(a) for a in aliases),
            )
        )
    return tuple(sorted(found, key=lambda c: c.name))


def split(text: str) -> tuple[str, str]:
    """``"/clear notes"`` → ``("clear", "notes")``; ``("", text)`` if not a command."""
    if not text.startswith("/"):
        return "", text
    name, _, arguments = text[1:].partition(" ")
    return name.strip(), arguments.strip()


async def load(harness: Harness) -> tuple[SlashCommand, ...]:
    """Ask a session what commands it has, without spending a turn.

    Unlike ``probe``, this needs no query: the list arrives with the control
    protocol's initialize response, so connecting is enough. It still starts the
    CLI, so a client should do it off the main thread.
    """
    options = ClaudeAgentOptions(**harness.options())
    async with ClaudeSDKClient(options=options) as client:
        info = await client.get_server_info()
    return parse((info or {}).get("commands"))

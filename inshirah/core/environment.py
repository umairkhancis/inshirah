"""What Claude Code actually loaded in this directory.

Inshirah replaces Claude Code's terminal, not its brain, so a project's
CLAUDE.md, ``.claude/skills``, ``.claude/agents``, ``.claude/settings.json``
hooks, ``.mcp.json`` servers and plugins all load exactly as they would under
``claude`` — none of it is reimplemented here.

The catch is that none of it is *visible*. A skill that failed to parse or an
MCP server that died on startup looks identical to one that is working, and a
surface that silently drops half a project's configuration is worse than one
that never supported it. The CLI reports what it resolved in its ``init``
message; this turns that into something a client can show.

``init`` only arrives once a turn starts, so what loaded is known after the
first message, not before — which is why ``probe`` exists for ``--check``.

One thing the CLI does not report at all is CLAUDE.md: ``memory_paths`` holds
only the auto-memory directory. The files are read — a project's memory reaches
the model — but nothing in ``init`` names them, so they are found by looking at
the filesystem instead. That is the single thing here Inshirah works out for
itself, and it is reported as "found on disk" rather than as something the CLI
confirmed.
"""

import asyncio
import pathlib
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
)

from .errors import SendFailed, failure_of

from .harness import Harness


# Where Claude Code looks for memory. The init message never mentions CLAUDE.md
# — it reports only the auto-memory directory — so these are found by looking,
# which is the one thing in this module Inshirah works out for itself.
MEMORY_FILENAMES = ("CLAUDE.md", "CLAUDE.local.md")
_MAX_ANCESTORS = 20


def find_memory_files(cwd: str) -> tuple[str, ...]:
    """CLAUDE.md files that apply to ``cwd``, nearest last.

    Project memory, then any inherited from parent directories (a package
    inside a monorepo gets the repo's too), plus the user-level one. Existence
    on disk is what is reported; whether the CLI read a given file is its
    decision, and it does not say.
    """
    found: list[str] = []
    user = pathlib.Path.home() / ".claude" / "CLAUDE.md"
    if user.is_file():
        found.append(str(user))

    project = pathlib.Path(cwd).expanduser()
    ancestors = [project, *project.parents[:_MAX_ANCESTORS]]
    for directory in reversed(ancestors):  # furthest first, project last
        for name in MEMORY_FILENAMES:
            candidate = directory / name
            if candidate.is_file() and str(candidate) not in found:
                found.append(str(candidate))
    return tuple(found)


@dataclass(frozen=True)
class Environment:
    """The project configuration one session resolved."""

    cwd: str = ""
    model: str = ""
    permission_mode: str = ""
    agents: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    slash_commands: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()
    memory_paths: tuple[str, ...] = ()  # the auto-memory directory
    claude_md: tuple[str, ...] = ()  # found on disk, not reported by the CLI
    mcp_servers: tuple[tuple[str, str], ...] = ()  # (name, status)

    @classmethod
    def from_init(
        cls, data: dict[str, Any], claude_md: tuple[str, ...] | None = None
    ) -> "Environment":
        servers = []
        for server in data.get("mcp_servers") or []:
            if isinstance(server, dict):
                servers.append((server.get("name", "?"), server.get("status", "unknown")))
            else:
                servers.append((str(server), "unknown"))
        memory = data.get("memory_paths") or {}
        cwd = data.get("cwd", "")
        return cls(
            claude_md=find_memory_files(cwd) if claude_md is None else claude_md,
            cwd=cwd,
            model=data.get("model", ""),
            permission_mode=data.get("permissionMode", ""),
            agents=tuple(data.get("agents") or ()),
            skills=tuple(data.get("skills") or ()),
            slash_commands=tuple(data.get("slash_commands") or ()),
            tools=tuple(data.get("tools") or ()),
            plugins=tuple(
                p.get("name", "?") if isinstance(p, dict) else str(p)
                for p in (data.get("plugins") or ())
            ),
            memory_paths=tuple(memory.values()) if isinstance(memory, dict) else tuple(memory),
            mcp_servers=tuple(servers),
        )

    @property
    def broken_mcp(self) -> tuple[str, ...]:
        """Servers the CLI could not start.

        Worth singling out: a dead MCP server is invisible otherwise — its tools
        simply never appear, and the agent looks merely unhelpful.
        """
        return tuple(name for name, status in self.mcp_servers if status != "connected")

    def summary(self) -> str:
        """One line, for a status bar or a toast."""
        parts = [
            f"{len(self.claude_md)} CLAUDE.md",
            f"{len(self.tools)} tools",
            f"{len(self.skills)} skills",
            f"{len(self.agents)} agents",
            f"{len(self.mcp_servers)} mcp",
        ]
        if self.broken_mcp:
            parts.append(f"⚠ {len(self.broken_mcp)} mcp failed")
        return " · ".join(parts)

    def report(self) -> str:
        """The full picture, for ``--check``."""

        def block(title: str, items: tuple[str, ...]) -> list[str]:
            if not items:
                return [f"{title}: none"]
            return [f"{title} ({len(items)}):", *(f"  - {i}" for i in items)]

        lines = [
            f"project        : {self.cwd}",
            f"model          : {self.model}",
            f"permission mode: {self.permission_mode}",
            "",
            *block("CLAUDE.md (found on disk — the CLI does not report these)", self.claude_md),
            "",
            *block("project memory directory", self.memory_paths),
            "",
            *block("skills", self.skills),
            "",
            *block("agents", self.agents),
            "",
            *block("plugins", self.plugins),
            "",
        ]
        if self.mcp_servers:
            lines.append(f"mcp servers ({len(self.mcp_servers)}):")
            lines += [f"  - {name}: {status}" for name, status in self.mcp_servers]
        else:
            lines.append("mcp servers: none")
        lines += ["", f"tools ({len(self.tools)}): {', '.join(self.tools)}"]
        if self.slash_commands:
            lines += ["", f"slash commands ({len(self.slash_commands)}): "
                          f"{', '.join(self.slash_commands[:20])}"
                          f"{' …' if len(self.slash_commands) > 20 else ''}"]
        if self.broken_mcp:
            lines += ["", f"WARNING: these mcp servers did not start: {', '.join(self.broken_mcp)}"]
        return "\n".join(lines)


async def probe(harness: Harness, timeout: float = 90.0) -> Environment:
    """Run one short turn, and report what it loaded — if it ran at all.

    Costs one short turn: the CLI does not send ``init`` until a query is in
    flight, so there is no way to ask what a directory would load for free.

    The turn is then read to its end rather than abandoned at ``init``, and that
    is the whole difference between a report and a diagnostic. ``init`` is the
    CLI describing the directory, and it arrives before anything has been sent
    anywhere — so a machine that has never signed in produces a complete,
    healthy-looking report of its skills, agents and MCP servers, and then fails
    on the user's first real message. Whether the turn *finished* is the only
    part of this that answers "will this work for me".
    """
    options = ClaudeAgentOptions(**harness.options())

    async def one_turn() -> Environment:
        loaded: Environment | None = None
        async with ClaudeSDKClient(options=options) as client:
            await client.query("hi")
            async for message in client.receive_response():
                if isinstance(message, SystemMessage) and message.subtype == "init":
                    loaded = Environment.from_init(message.data)
                elif isinstance(message, ResultMessage) and message.is_error:
                    raise SendFailed(failure_of(message))
        if loaded is None:
            raise RuntimeError("the session ended before reporting what it loaded")
        return loaded

    return await asyncio.wait_for(one_turn(), timeout=timeout)

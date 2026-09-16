"""How much of Claude Code to turn on.

Inshirah is a *surface*, not a second agent. Everything under it — the agent
preset, the tool suite, CLAUDE.md, ``.claude/`` settings, ``.mcp.json``, skills,
plugins, hooks — is Claude Code's, unchanged. So this module is mostly about
*not* opting out: the SDK's defaults already are Claude Code, and turning the
harness on meant deleting four deliberate opt-outs rather than adding anything.

``permission_mode`` and the tool lists are the knobs for tightening it, and they
only ever narrow what the agent may do; see ``inshirah/tui/__main__.py`` for the
command-line flags that set them.
"""

import os
from dataclasses import dataclass, field
from typing import Any

# Ask the CLI for its own prompt and its own tools, rather than naming either.
# A literal list would drift the moment Claude Code gains a tool.
CLAUDE_CODE: dict[str, str] = {"type": "preset", "preset": "claude_code"}

PERMISSION_MODES = (
    "auto",  # Claude Code's auto mode — the default here
    "default",
    "acceptEdits",
    "plan",
    "dontAsk",
    "bypassPermissions",
)


@dataclass(frozen=True)
class Harness:
    """The Claude Code configuration a conversation runs under."""

    permission_mode: str = "auto"
    allowed_tools: tuple[str, ...] = ()  # auto-approved, never prompted
    disallowed_tools: tuple[str, ...] = ()  # removed from the model's context
    cwd: str | None = None  # None -> the directory Inshirah was launched from
    add_dirs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.permission_mode not in PERMISSION_MODES:
            raise ValueError(
                f"unknown permission mode {self.permission_mode!r}; "
                f"expected one of {', '.join(PERMISSION_MODES)}"
            )

    @property
    def project(self) -> str:
        """The directory Claude Code treats as the project.

        This is what decides which CLAUDE.md and which ``.claude/`` settings are
        loaded — cwd, not ``setting_sources``, is what governs project memory.
        """
        return self.cwd or os.getcwd()

    def options(self) -> dict[str, Any]:
        """The ClaudeAgentOptions fields that decide how much harness is on."""
        return {
            "tools": CLAUDE_CODE,  # every default Claude Code tool
            "system_prompt": CLAUDE_CODE,  # Claude Code's own agent preset
            "setting_sources": None,  # user + project + local, and CLAUDE.md
            "cwd": self.project,  # the real project: memory, .claude/, .mcp.json
            "permission_mode": self.permission_mode,
            "allowed_tools": list(self.allowed_tools),
            "disallowed_tools": list(self.disallowed_tools),
            "add_dirs": list(self.add_dirs),
        }

"""``!command`` — run a shell command and put its output in the conversation.

Claude Code's REPL has this; the SDK does not, because it drives the CLI in
stream-json mode rather than through the REPL, so a leading ``!`` arrives as
ordinary prompt text. (The model recognises the convention and will *act* as
though a command ran, which makes the omission worse than it looks.)

Inshirah gets something Claude Code's version cannot offer: the output lands in
the transcript as an ordinary message, so it can be edited before the model ever
reads it, or have a thread branched off it. Piping in a long build log and then
cutting it down to the three lines that matter is the point.

No permission prompt guards this. The command is the one the user just typed, so
gating it would be asking them to approve their own keystrokes — the same call
Claude Code makes.
"""

import asyncio
from dataclasses import dataclass

DEFAULT_TIMEOUT = 30.0

# A transcript is context, and context is finite: `!cat` on a large file would
# otherwise push the actual conversation out of the window.
MAX_LINES = 100
MAX_CHARS = 8_000


@dataclass(frozen=True)
class ShellResult:
    command: str
    output: str
    exit_code: int
    truncated: bool = False

    @property
    def failed(self) -> bool:
        return self.exit_code != 0

    def as_message(self) -> str:
        """How the command and its output read in the transcript.

        Shaped like a terminal session because that is what it is, and because
        the model reads it as one without being told.
        """
        lines = [f"$ {self.command}"]
        if self.output:
            lines.append(self.output)
        if self.truncated:
            lines.append(f"… output truncated at {MAX_LINES} lines")
        if self.failed:
            lines.append(f"(exit {self.exit_code})")
        return "\n".join(lines)


def _clip(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    truncated = False
    if len(lines) > MAX_LINES:
        lines, truncated = lines[:MAX_LINES], True
    clipped = "\n".join(lines)
    if len(clipped) > MAX_CHARS:
        clipped, truncated = clipped[:MAX_CHARS], True
    return clipped.rstrip(), truncated


async def run(
    command: str, cwd: str, timeout: float = DEFAULT_TIMEOUT
) -> ShellResult:
    """Run ``command`` in ``cwd``, capturing stdout and stderr together.

    Never raises for a failing command — a non-zero exit is an ordinary result
    worth putting in the conversation, often the most interesting one.
    """
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:  # e.g. cwd no longer exists
        return ShellResult(command, f"could not run: {exc}", 127)

    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return ShellResult(command, f"timed out after {timeout:g}s", 124)

    output, truncated = _clip(stdout.decode(errors="replace"))
    return ShellResult(command, output, process.returncode or 0, truncated)

"""What a first run needs, and what to say when it is missing.

Inshirah installs as a Python package, but it does not talk to any model itself:
it drives Claude Code, which is a separate program, installed separately, with
its own login. So the one failure a new user is most likely to hit is not a bug
in this code — it is a machine where Claude Code is absent or not signed in, and
the SDK's own exception for that says ``Claude Code not found`` and stops.

That sentence is correct and useless. Someone who just ran ``uvx inshirah`` does
not know that a Node CLI is involved, let alone which one, so this module turns
the failure into the commands that fix it.

In practice the missing-binary case is now the rarer of the two: the Agent SDK
bundles a copy of the CLI, so an install nearly always finds one. What it cannot
bundle is a *session*, which is why being signed out is the failure a new user
actually meets, and why it is told apart from the other one rather than folded
into a single "check your setup".

Why translate the failure rather than check at startup: the SDK does the finding
(PATH, a bundled copy, several install locations), and a second search here
would be a copy that drifts. More to the point, a check can only see whether the
binary exists — "installed but never logged in" looks identical to a working
install until a turn actually runs. Failing well covers both; detecting covers
one, later, and wrongly.

Nothing here phones home, and nothing here is telemetry — the whole diagnosis
happens on the user's machine, from an exception they already have.
"""

import pathlib
import platform
import shutil

import claude_agent_sdk
from claude_agent_sdk import CLINotFoundError

CLI_PACKAGE = "@anthropic-ai/claude-code"

MISSING = f"""\
Claude Code is not installed, and Inshirah runs on top of it.

    npm install -g {CLI_PACKAGE}
    claude          # once, to sign in

Then start Inshirah again. Inshirah never asks for a key of its own: it uses
the Claude Code you just signed in to, on this machine."""

SIGNED_OUT = """\
Claude Code is here, but this machine is not signed in to it.

    inshirah --login    # sign in, then quit Claude Code with /exit

It says `inshirah --login` rather than `claude` because the copy of Claude Code
that came with Inshirah is inside the install, not on your PATH — telling you to
run a command you do not have is not advice. The sign-in is Anthropic's, in your
browser; Inshirah has no account and no key of its own, and never sees it."""

# Substrings the CLI puts in a failed turn when the problem is the account
# rather than the request. Matched on text because the SDK reports a failed
# result as a message, not as a typed exception.
_SIGNED_OUT_SIGNS = (
    "invalid api key",
    "authentication_error",
    "please run /login",
    "oauth token has expired",
    "unauthorized",
)


def explain(exc: BaseException) -> str | None:
    """Actionable text if this failure is really a setup problem, else None.

    Returning None is the common case and means "not mine" — the caller should
    show the error it already has rather than guess.
    """
    if isinstance(exc, CLINotFoundError):
        return MISSING
    text = str(exc).lower()
    if any(sign in text for sign in _SIGNED_OUT_SIGNS):
        return SIGNED_OUT
    return None


def claude_binary() -> str | None:
    """The Claude Code that Inshirah will actually run, or None.

    Deliberately mirrors the top of the SDK's own search — the bundled copy
    first, then PATH — because signing in has to happen in the same program the
    conversations run in. The stakes are lower than that makes it sound: the
    credentials land in ``~/.claude`` and every copy on the machine reads them,
    so picking the other one would still work. Getting the *order* wrong is what
    would be confusing, not the choice itself.

    Only used to hand the user an interactive session. Deciding whether a
    session can start is still the SDK's job, and still answered by trying.
    """
    name = "claude.exe" if platform.system() == "Windows" else "claude"
    bundled = pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / name
    if bundled.is_file():
        return str(bundled)
    return shutil.which(name)

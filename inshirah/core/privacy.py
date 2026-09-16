"""What leaves this machine, stated by the program rather than by its README.

The claim Inshirah has to earn is narrow and checkable: there is no Inshirah
account, no Inshirah server, and no telemetry. Conversations are files in the
user's home directory, and the only thing that crosses the network is the model
traffic Claude Code was already sending before Inshirah was installed.

A README can assert that. This prints it from the installed code, with the real
paths for the machine it is running on, which at least fails loudly if it ever
stops being true — and ``tests/test_privacy.py`` holds the package to it by
refusing to let any network client be imported into it.

The usage counts in :mod:`inshirah.core.usage` are the one thing here that is
kept for the project's benefit rather than the user's, so they are named in this
statement rather than mentioned in a changelog. They are integers in a file on
this disk; the program still cannot send them, and the form that collects them
is opened in the user's browser with the numbers visible, by the user, or not at
all.

Kept in ``core`` rather than in the CLI because it is a property of the product,
not of one front end: a web client would have to make the same statement, and
would have to make it differently the moment it stopped being true of itself.
"""

import pathlib

from . import usage
from .config import PROVIDER, PROVIDER_NAME

REPORT = """\
What leaves this machine

  Inshirah has no account, no server and no telemetry. Nothing is
  collected about you and nothing is ever sent anywhere on its own —
  this program has no way to send anything. The one thing it can do is
  open a page in your browser, and only when you ask it to.

  Model traffic       {destination}
                      via your own Claude Code install, signed in as you,
                      billed to you. Inshirah never sees a key of yours.

  Conversations       {conversations}
                      plain JSON on this disk. Delete the directory and
                      they are gone.

  Usage counts        {usage}
                      integers, written as you work: how many sessions,
                      edits, threads, exports. Never prompts, replies,
                      file names, paths, project directories, or any
                      identifier for you or this machine. `inshirah
                      --stats` prints the file and offers to open a form
                      with the numbers filled in, which you submit —
                      or close. {disable}=1 keeps none of it.

  Exports             ./exports, only when you press ctrl+x.

  Your code           read and written by Claude Code's tools, in the
                      directory you launched in, exactly as `claude` would.

  Verify it           this package imports no HTTP client at all; the only
                      process it starts is Claude Code. `pip show inshirah`
                      for the source, and tests/test_privacy.py is the
                      check that keeps it that way."""


def report(conversations: pathlib.Path | str) -> str:
    """The statement, with this machine's real paths filled in."""
    destination = (
        PROVIDER.env.get("ANTHROPIC_BASE_URL")
        or f"the Anthropic API ({PROVIDER_NAME})"
    )
    return REPORT.format(
        destination=destination,
        conversations=pathlib.Path(conversations).expanduser(),
        usage=usage.path(),
        disable=usage.DISABLE,
    )

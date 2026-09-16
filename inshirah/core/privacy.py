"""What leaves this machine, stated by the program rather than by its README.

The claim Inshirah has to earn is narrow and checkable: there is no Inshirah
account, no Inshirah server, and no telemetry. Conversations are files in the
user's home directory, and the only thing that crosses the network is the model
traffic Claude Code was already sending before Inshirah was installed.

A README can assert that. This prints it from the installed code, with the real
paths for the machine it is running on, which at least fails loudly if it ever
stops being true — and ``tests/test_privacy.py`` holds the package to it by
refusing to let any network client be imported into it.

Kept in ``core`` rather than in the CLI because it is a property of the product,
not of one front end: a web client would have to make the same statement, and
would have to make it differently the moment it stopped being true of itself.
"""

import pathlib

from .config import PROVIDER, PROVIDER_NAME

REPORT = """\
What leaves this machine

  Inshirah has no account, no server and no telemetry. Nothing is sent to
  the people who wrote it — there is nowhere for it to be sent to.

  Model traffic       {destination}
                      via your own Claude Code install, signed in as you,
                      billed to you. Inshirah never sees a key of yours.

  Conversations       {conversations}
                      plain JSON on this disk. Delete the directory and
                      they are gone.

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
    )

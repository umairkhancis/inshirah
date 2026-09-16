"""Inshirah — a conversation whose messages can be edited in place and branched.

The package is split so that a client is a thin shell over a headless engine:

    inshirah.core   the engine — conversation state, transcript, provider config.
                    Imports nothing from any client and touches no terminal.
    inshirah.tui    the Textual client.

A web app is a sibling of ``inshirah.tui``: it imports the same ``inshirah.core``
names and renders them differently. Nothing in ``core`` needs to know it exists.
"""

# The one place the version lives. pyproject reads it from here (dynamic
# version), so a release cannot ship a package whose --version disagrees with
# the wheel someone installed.
__version__ = "0.1.1"

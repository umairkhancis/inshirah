"""What can go wrong, typed so a client can react without parsing messages.

The TUI shows every failure the same way — a red toast — so it never needed to
tell them apart. An HTTP client does: "no such message" is a 404 and "a turn is
already running" is a 409, and a web layer that has to match on error *text* to
pick a status code is a seam in the wrong place.

``MessageNotFound`` and ``NothingToEdit`` subclass ``ValueError`` because that is
what the edit methods raised before they were named.
"""

from typing import Any


def failure_of(result: Any) -> str:
    """The text of a ``ResultMessage`` that reports a failed turn.

    Lives beside ``SendFailed`` because it is only ever the argument to one: the
    CLI does not raise when a turn fails, it *reports* the failure as the last
    message of the turn, and both the places that run a turn — a real send and
    ``probe`` — have to notice the same way.
    """
    return "; ".join(result.errors or []) or result.result or "request failed"


class InshirahError(Exception):
    """Base for everything this package raises deliberately."""


class SendFailed(InshirahError):
    """A turn that never happened — its entries are rolled back."""


class ConversationBusy(InshirahError):
    """A turn is already running on this tree.

    Sends queue behind each other, so this is only raised by the synchronous
    mutations (editing, branching), which cannot wait for the lock and must not
    rewrite the transcript out from under a turn in flight.
    """


class MessageNotFound(InshirahError, ValueError):
    """No message with that uuid in the stored transcript."""


class NothingToEdit(InshirahError, ValueError):
    """The conversation has not started, so there is nothing to address yet."""


class ConversationNotFound(InshirahError):
    """No conversation tree with that id, live or stored."""

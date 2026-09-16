"""The terminal client — one of several possible front ends over ``inshirah.core``.

Everything here is presentation: widgets, key bindings, and the choice of which
core call a keystroke maps to. Conversation state lives in the core.
"""

from .app import InshirahApp

__all__ = ["InshirahApp"]

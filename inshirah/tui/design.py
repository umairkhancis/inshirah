"""The design system: one palette, expressed as Textual theme tokens.

Nothing else in the app names a colour. Every widget styles itself from semantic
tokens, so the whole surface re-skins by swapping a theme and a light terminal
is not an afterthought.

Two families of token:

    the standard ones   ``$primary`` you, ``$success`` the agent, ``$secondary``
                        the shell, ``$accent`` what you are acting on now.
    the rail ones       ``$rail``, ``$rail-text``, ``$rail-muted``,
                        ``$rail-active``. The conversation rail keeps its deep
                        ground in both themes — the way Slack's does — because
                        it is chrome you navigate by, not paper you read.
"""

from textual.theme import Theme

_RAIL_DARK = {
    "rail": "#241A33",
    "rail-raised": "#2F2342",
    "rail-text": "#E7E1F0",
    "rail-muted": "#9C8FB4",
    "rail-active": "#4B3272",
    "rail-edge": "#170F22",
}

DUSK = Theme(
    name="inshirah-dusk",
    dark=True,
    primary="#8B6DFF",  # you
    secondary="#57B9D3",  # the shell
    success="#4CC38A",  # the agent
    accent="#F0A860",  # what you are acting on right now
    warning="#F0A860",
    error="#E4677B",
    foreground="#DDE1E9",
    background="#0F1117",
    surface="#161A22",
    panel="#1E2430",
    boost="#FFFFFF0A",
    variables={
        **_RAIL_DARK,
        "border": "#2A3140",
        "border-blurred": "#232935",
        "block-cursor-foreground": "#0F1117",
        "block-cursor-background": "#8B6DFF",
        "block-cursor-text-style": "none",
        "input-selection-background": "#8B6DFF 35%",
        "footer-background": "#0F1117",
        "footer-key-foreground": "#8B6DFF",
        "footer-description-foreground": "#7C8799",
        "scrollbar": "#252C39",
        "scrollbar-hover": "#303947",
        "scrollbar-active": "#8B6DFF",
        "scrollbar-background": "#0F1117",
        "text-muted": "#8792A4",
    },
)

DAY = Theme(
    name="inshirah-day",
    dark=False,
    primary="#5B3DF5",
    secondary="#1F7F9B",
    success="#1F8A5B",
    accent="#B06A10",
    warning="#B06A10",
    error="#C0334C",
    foreground="#1B2029",
    background="#FFFFFF",
    surface="#F7F7FA",
    panel="#EEEEF3",
    boost="#00000008",
    variables={
        # The rail stays dark in daylight: it is chrome, not paper.
        **_RAIL_DARK,
        "rail": "#3A2352",
        "rail-raised": "#4A2F68",
        "rail-active": "#5B3DF5",
        "rail-edge": "#291739",
        "border": "#DDDDE5",
        "border-blurred": "#E8E8EE",
        "block-cursor-foreground": "#FFFFFF",
        "block-cursor-background": "#5B3DF5",
        "block-cursor-text-style": "none",
        "input-selection-background": "#5B3DF5 25%",
        "footer-background": "#EEEEF3",
        "footer-key-foreground": "#5B3DF5",
        "footer-description-foreground": "#5C6373",
        "scrollbar": "#DDDDE5",
        "scrollbar-hover": "#C7C7D2",
        "scrollbar-active": "#5B3DF5",
        "scrollbar-background": "#EEEEF3",
        "text-muted": "#5C6373",
    },
)

THEMES = (DUSK, DAY)

# The rail tokens are ours, not Textual's, so the stylesheet references names no
# built-in theme defines. Textual parses the CSS before any theme is applied, so
# these are handed to it up front through ``App.get_theme_variable_defaults``;
# each theme's own values then override them.
VARIABLE_DEFAULTS = dict(_RAIL_DARK)

# Glyphs belong to the design system too: the same idea must not be drawn two
# different ways in the rail and in the transcript.
GLYPHS = {
    "user": "❯",
    "assistant": "✦",
    "shell": "$",
    "held": "◌",
    "thread": "⤷",
    "tool": "⚙",
    "dot": "●",
    "new": "+",
    "close": "✕",
    "hash": "#",
}


def register(app) -> None:
    """Make both themes available, and start in the dark one."""
    for theme in THEMES:
        app.register_theme(theme)
    app.theme = DUSK.name

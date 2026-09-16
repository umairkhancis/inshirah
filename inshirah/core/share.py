"""Handing the counts over: a prefilled form, opened in the user's own browser.

The constraint this module is shaped by is that Inshirah has no way to send
anything. There is no HTTP client in the package, ``tests/test_privacy.py``
fails the build if one is imported, and that test is the reason anyone believes
the README. Adding a sender to collect usage figures would trade the one asset
the project has for a number.

So nothing is sent from here. This turns the counts into a URL for a Google Form
whose fields are already filled in, and ``webbrowser`` hands that URL to the
browser the user already trusts. They see the numbers in the form, in their own
words, and press Submit — or close the tab, which is a refusal that costs them
nothing and leaves no trace anywhere.

That is one click more than a POST would have been, and it buys three things a
POST cannot. The payload is visible to the person sending it, at the moment of
sending, rather than described to them in a changelog. There is no endpoint, so
there is nothing to secure, nothing to keep up, and no server logs quietly
accruing IP addresses next to the data. And the claim "this program cannot send
anything on its own" stays literally true, checkable by reading the imports.

The query string is assembled by hand below rather than with ``urllib.parse``,
which would be the obvious tool. ``urllib`` is on the list of modules the
privacy test refuses to let into this package — the list is about
``urllib.request``, which opens sockets, but it matches on the top-level name,
and six lines of percent-encoding are a smaller price than an exception carved
into the one test that makes the promise enforceable.
"""

import os
import string
import webbrowser
from typing import Any

# The form that collects these. Empty means unconfigured — a fork, or a build
# made before there was anywhere to send them — and --stats then shows the
# numbers and says there is nowhere for them to go, rather than opening a broken
# link. See docs/stats-form.md for where these two values come from.
FORM_ID = "1FAIpQLSf6Hdhw-00ik5cZZoOL4sHFiT5mi3X_w-y2SVcuGLaHC0WsGw"

# Payload key -> the form's own name for that question. Read off a pre-filled
# link by scripts/stats_form.py; never typed out by hand, because a transposed
# digit here is a number silently landing in the wrong column forever.
FIELDS: dict[str, str] = {
    "inshirah": "entry.1217492188",
    "os": "entry.1206831720",
    "days": "entry.699600569",
    "sessions": "entry.1547799303",
    "conversations": "entry.892847873",
    "turns": "entry.1334269880",
    "edits": "entry.1770391780",
    "edits_user": "entry.76761732",
    "edits_assistant": "entry.1417039738",
    "resends": "entry.320753340",
    "threads": "entry.1421584017",
    "shell_holds": "entry.1497975802",
    "exports": "entry.1315725563",
    "sessions_2plus_edits": "entry.1257565183",
}

# Overridable so the form can be replaced, or tried out, without a release.
FORM_ID_ENV = "INSHIRAH_FORM_ID"

FORM = "https://docs.google.com/forms/d/e/{form}/viewform"

_SAFE = frozenset(string.ascii_letters + string.digits + "-._~")


def _quote(value: str) -> str:
    """Percent-encode one query component. See the module docstring."""
    out = []
    for character in value:
        if character in _SAFE:
            out.append(character)
        else:
            out.extend(f"%{byte:02X}" for byte in character.encode("utf-8"))
    return "".join(out)


def form_id() -> str:
    return os.environ.get(FORM_ID_ENV) or FORM_ID


def configured() -> bool:
    """Whether there is somewhere for the numbers to go."""
    return bool(form_id() and FIELDS)


def url(payload: dict[str, Any]) -> str:
    """The form, with every field this payload has an answer for filled in.

    Keys the form does not have a question for are dropped rather than raising:
    a form built before a counter existed should keep working, collecting the
    fields it knows about, until someone gets round to adding the question.
    """
    pairs = [("usp", "pp_url")]
    pairs += [
        (FIELDS[key], str(value))
        for key, value in payload.items()
        if key in FIELDS
    ]
    query = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in pairs)
    return f"{FORM.format(form=form_id())}?{query}"


def open_form(payload: dict[str, Any], opener=None) -> bool:
    """Open the prefilled form. False if this machine has no browser to open.

    ``opener`` is resolved here rather than defaulted in the signature: a
    default argument binds ``webbrowser.open`` once, at import, and a caller who
    wanted to watch what this does without a browser appearing could not get in
    front of it. That caller is every test of the flow above this function.
    """
    try:
        return bool((opener or webbrowser.open)(url(payload)))
    except Exception:
        return False


CONSENT = """\
  Send these numbers to the people who wrote Inshirah?

  There is no Inshirah server, so this works the only way it can: your
  browser opens a form with exactly the numbers above already filled in,
  you read them there, and you press Submit. Nothing is sent by this
  program, and closing the tab sends nothing at all.

  It is the only way anyone finds out whether editing in place is
  something people actually use, or an idea that sounded good."""

UNCONFIGURED = """\
  There is nowhere to send these yet — no form is configured in this
  build. The numbers above are yours; the file they came from is plain
  JSON and you are welcome to do anything you like with it."""

NOT_INTERACTIVE = """\
  Not asking, because this is not an interactive terminal. Run
  `inshirah --stats` yourself if you would like to send them."""

SENT = """\
  Opened your browser. The numbers are filled in; press Submit to send
  them, or close the tab and nothing happens."""

NO_BROWSER = """\
  Could not open a browser on this machine. This is the whole of it —
  paste it somewhere that has one, or do not:

    {url}"""

DECLINED = "  Not sent."

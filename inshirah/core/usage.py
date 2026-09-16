"""Usage counts, kept on this machine, and sent only if the user sends them.

This is the one part of Inshirah that exists for the people who wrote it rather
than for the person running it, so it is worth being exact about what it is.

It is a JSON file in the user's home directory holding integers: how many
sessions were started, how many messages were edited, how many threads were
branched. It is written as the app is used, the way a shell writes history. The
user can read it with ``inshirah --stats``, stop it with ``INSHIRAH_NO_USAGE=1``
and delete it with ``rm``.

It is not telemetry, because nothing here can transmit. There is no HTTP client
in this package and this module does not add one — :mod:`inshirah.core.share`
turns these numbers into a URL, and the user's own browser is what carries them,
after they have read them twice: once in the terminal, once in the form.

What it never holds is content. Not prompts, not replies, not file names, not
paths, not the project directory, not a machine id. The question the numbers
exist to answer is "did editing in place actually get used", and a count answers
it, so a count is all there is. Anything richer would contradict what
``privacy.py`` already says out loud, and the value of that statement is that it
has never needed a footnote.

Two of the counters need a word.

``edited_sessions`` buckets how many sessions had 0, 1, 2 or more edits in them.
The number that says whether the idea landed is not how many edits happened —
one person editing forty times in a single sitting and never returning is not
adoption — it is how many separate sittings had more than a couple.

And the session in progress is held apart from the totals so that it can be
folded into those buckets at the *start* of the next run rather than the end of
this one. An app that is killed, that crashes, or whose terminal window is
simply closed never gets to run its own cleanup, and a counter that survives
only a graceful exit would undercount precisely the sessions worth knowing
about.
"""

import json
import os
import pathlib
import platform
from datetime import date
from typing import Any

from inshirah import __version__

DIRECTORY = pathlib.Path("~/.inshirah")
FILENAME = "usage.json"

# Opting out of a local file is not the same as opting out of telemetry — there
# is no telemetry to opt out of — but people who would rather their machine not
# keep a tally should not have to argue for it, and honouring one env var is
# cheaper than the conversation.
DISABLE = "INSHIRAH_NO_USAGE"

VERSION = 1

# Every counter there is. A fixed tuple rather than whatever a caller passes,
# because the payload ``share`` builds is derived from this list: a new event is
# a deliberate edit to this line, and it shows up in ``--stats``, where the user
# reads it, before it could ever show up in a form.
TOTALS = (
    "sessions",
    "conversations",
    "turns",
    "edits",
    "edits_user",
    "edits_assistant",
    "resends",
    "threads",
    "shell_holds",
    "exports",
)

# The counters a single session also keeps, so a session can be bucketed by how
# much editing happened in it.
PER_SESSION = ("turns", "edits", "threads")

BUCKETS = ("0", "1", "2", "3+")


def enabled() -> bool:
    return not os.environ.get(DISABLE)


def path() -> pathlib.Path:
    """Read through ``DIRECTORY`` at call time so a test can move it."""
    return DIRECTORY.expanduser() / FILENAME


def blank() -> dict[str, Any]:
    return {
        "version": VERSION,
        "since": date.today().isoformat(),
        "totals": dict.fromkeys(TOTALS, 0),
        "edited_sessions": {},
        "session": dict.fromkeys(PER_SESSION, 0),
    }


def _ints(source: Any, names: tuple[str, ...]) -> dict[str, int]:
    got = source if isinstance(source, dict) else {}
    return {n: got[n] if isinstance(got.get(n), int) else 0 for n in names}


def load() -> dict[str, Any]:
    """The file as a well-formed record, whatever is actually on disk.

    Nothing here may raise. A counter is a side effect of doing something else —
    editing a message, branching a thread — and a hand-edited, truncated or
    stale file is not a reason to fail the thing the user actually asked for. An
    unreadable file is treated as no file, which loses counts and breaks
    nothing.
    """
    try:
        data = json.loads(path().read_text())
    except Exception:
        return blank()
    if not isinstance(data, dict) or data.get("version") != VERSION:
        return blank()
    record = blank()
    since = data.get("since")
    if isinstance(since, str) and since:
        record["since"] = since
    record["totals"] = _ints(data.get("totals"), TOTALS)
    record["session"] = _ints(data.get("session"), PER_SESSION)
    buckets = data.get("edited_sessions")
    if isinstance(buckets, dict):
        record["edited_sessions"] = {
            str(k): v
            for k, v in buckets.items()
            if str(k) in BUCKETS and isinstance(v, int)
        }
    return record


def save(data: dict[str, Any]) -> None:
    """Write the record, atomically, and never raise.

    Atomically because two things write this file: an app doing its work, and
    ``--serve``, which gives every browser tab its own process. A half-written
    file would be discarded by ``load`` on the next read, which is survivable,
    but ``os.replace`` makes it not happen at all. Interleaved *processes* still
    lose the odd count — last writer wins — and that is an acceptable error for
    a number whose job is to say roughly how much something was used.
    """
    try:
        target = path()
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = target.with_name(target.name + ".writing")
        scratch.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(scratch, target)
    except Exception:
        pass


def record(*events: str) -> None:
    """Count one or more things that just happened.

    Variadic because the events come in sets — an edit is an ``edits`` and an
    ``edits_user`` — and one call is one read-modify-write rather than two.
    """
    if not enabled():
        return
    counted = [e for e in events if e in TOTALS]
    if not counted:
        return
    data = load()
    for event in counted:
        data["totals"][event] = data["totals"].get(event, 0) + 1
        if event in PER_SESSION:
            data["session"][event] = data["session"].get(event, 0) + 1
    save(data)


def record_edit(role: str) -> None:
    """One edit, attributed to whose message it was.

    Which one it was is the interesting half. Editing your own question is a
    thing every chat surface offers; editing the model's reply and having the
    model never see what it originally said is the thing this app is for.
    """
    record("edits", "edits_assistant" if role == "assistant" else "edits_user")


def bucket_of(edits: int) -> str:
    return str(edits) if edits < 3 else "3+"


def _fold(data: dict[str, Any]) -> None:
    """Move the session held in ``data`` into the histogram, in place.

    Guarded on there having *been* a previous session: on the very first run
    there is nothing to fold, and folding anyway would invent a session that
    never happened and bias the "0 edits" bucket forever.
    """
    if data["totals"].get("sessions", 0) == 0:
        return
    label = bucket_of(data["session"].get("edits", 0))
    data["edited_sessions"][label] = data["edited_sessions"].get(label, 0) + 1


def start_session() -> None:
    """Begin a run. Called once, by whichever client is starting."""
    if not enabled():
        return
    data = load()
    _fold(data)
    data["totals"]["sessions"] = data["totals"].get("sessions", 0) + 1
    data["session"] = dict.fromkeys(PER_SESSION, 0)
    save(data)


def days_since(since: str) -> int:
    try:
        return max((date.today() - date.fromisoformat(since)).days, 0)
    except Exception:
        return 0


def current() -> dict[str, Any]:
    """The record including the session in progress, without writing it.

    ``--stats`` is usually run from inside a session or right after one, and a
    report that silently omitted the sitting the user just had would be the
    first thing they noticed was wrong.
    """
    data = load()
    _fold(data)
    return data


def summary() -> dict[str, Any]:
    """The numbers, as the fixed set of fields that may ever be shared.

    Written out key by key rather than splatted from ``TOTALS`` so that what
    leaves is legible in one screenful to anyone auditing this file — which is
    the only reason to trust it.
    """
    data = current()
    totals = data["totals"]
    buckets = data["edited_sessions"]
    return {
        "inshirah": __version__,
        "os": platform.system(),
        "days": days_since(data["since"]),
        "sessions": totals["sessions"],
        "conversations": totals["conversations"],
        "turns": totals["turns"],
        "edits": totals["edits"],
        "edits_user": totals["edits_user"],
        "edits_assistant": totals["edits_assistant"],
        "resends": totals["resends"],
        "threads": totals["threads"],
        "shell_holds": totals["shell_holds"],
        "exports": totals["exports"],
        "sessions_2plus_edits": sum(
            count for label, count in buckets.items() if label in ("2", "3+")
        ),
    }


REPORT = """\
What this copy of Inshirah has counted

  since {since}, {days} days ago — {file}

  Sessions              {sessions}
  Conversations         {conversations}
  Turns                 {turns}

  Messages edited       {edits}
    a reply of the model's   {edits_assistant}
    a question of yours      {edits_user}
  Sessions with 2+ edits  {sessions_2plus_edits} of {sessions}

  Threads branched      {threads}
  !command output held  {shell_holds}
  Exports written       {exports}

  Numbers only. No prompts, no replies, no file names, no paths, no
  project directories, no identifier for this machine or for you.
  Set {disable}=1 to keep none of it; delete the file to forget it."""


def report() -> str:
    """The counts, for a person, with this machine's real path in them."""
    return REPORT.format(
        disable=DISABLE,
        file=path(),
        since=current()["since"],
        **summary(),
    )


def reset() -> None:
    """Forget everything counted so far."""
    save(blank())

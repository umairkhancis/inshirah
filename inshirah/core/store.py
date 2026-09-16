"""A SessionStore that can rewrite history in place.

The SDK mirrors every transcript line to ``append()``. When ``resume`` is paired
with ``session_store``, it calls ``load()`` *before* spawning the CLI and
materializes whatever we return into a temp config dir the subprocess resumes
from. So the list we hand back from ``load()`` is, verbatim, the conversation
the model is about to see.

That makes editing a message a plain list mutation — no forking, no new session
id, and no writing Claude Code's private JSONL behind its back.

Editing truncates everything after the edited message, and that is not merely
tidiness: a fact usually appears in several later messages too, and a stale copy
left upstream contradicts the edit. Models resolve that contradiction against
the edit (Claude's safeguards may refuse the turn outright), so the edited
message must become the end of the conversation.
"""

from typing import Any

from claude_agent_sdk import SessionKey, SessionStoreEntry


def _key(key: SessionKey) -> str:
    subpath = key.get("subpath")
    return f"{key['session_id']}/{subpath}" if subpath else key["session_id"]


def _message(entry: SessionStoreEntry) -> dict[str, Any]:
    message = entry.get("message")  # type: ignore[assignment]
    return message if isinstance(message, dict) else {}


def text_of(entry: SessionStoreEntry) -> str:
    content = _message(entry).get("content")
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return content if isinstance(content, str) else ""


# How the CLI records a slash command it ran locally. The command itself arrives
# as a user entry wrapping the typed text in tags, its output as a `system`
# entry, and a caveat line for the model's benefit marked ``isMeta``. None of
# that is written for a reader, so it is unwrapped here rather than shown raw.
COMMAND_OUTPUT = "local_command"


def _tagged(text: str, tag: str) -> str | None:
    opening, closing = f"<{tag}>", f"</{tag}>"
    start = text.find(opening)
    end = text.find(closing, start + len(opening))
    if start == -1 or end == -1:
        return None
    return text[start + len(opening) : end].strip()


def is_meta(entry: SessionStoreEntry) -> bool:
    """Plumbing the CLI writes for the model, not a message anyone sent."""
    return bool(entry.get("isMeta"))


def command_of(entry: SessionStoreEntry) -> str | None:
    """``/model gpt`` for the entry recording a slash command, else None."""
    raw = text_of(entry)
    name = _tagged(raw, "command-name")
    if name is None:
        return None
    arguments = _tagged(raw, "command-args") or ""
    return f"{name} {arguments}".strip()


def is_command_output(entry: SessionStoreEntry) -> bool:
    return entry.get("type") == "system" and entry.get("subtype") == COMMAND_OUTPUT


def command_output_of(entry: SessionStoreEntry) -> str:
    content = entry.get("content")
    if not isinstance(content, str):
        return ""
    return _tagged(content, "local-command-stdout") or content.strip()


def presentation(entry: SessionStoreEntry) -> tuple[str, str]:
    """``(role, text)`` as a reader should see this entry.

    Slash commands are the reason this is not simply the entry's own type and
    text: the CLI records what you typed and what it printed in shapes meant for
    the transcript, and showing those verbatim puts XML on screen where a
    command and its output belong.
    """
    if is_command_output(entry):
        return "command", command_output_of(entry)
    if (typed := command_of(entry)) is not None:
        return "user", typed
    return str(entry.get("type", "")), text_of(entry)


def _blocks(entry: SessionStoreEntry, kind: str) -> list[dict[str, Any]]:
    content = _message(entry).get("content")
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == kind]


def tool_calls_of(entry: SessionStoreEntry) -> list[dict[str, Any]]:
    """The tools this entry asked to run, as ``{"name", "input"}``.

    Under the full harness most of what the agent does is a tool call, and an
    assistant entry can hold *only* a tool_use — no text at all. Rendering by
    text alone leaves the agent apparently silent while it edits your files.
    """
    return [
        {"name": b.get("name", "tool"), "input": b.get("input") or {}}
        for b in _blocks(entry, "tool_use")
    ]


def is_tool_result(entry: SessionStoreEntry) -> bool:
    """A transcript line that is only a tool handing its output back."""
    return bool(_blocks(entry, "tool_result")) and not text_of(entry)


# Which argument identifies a tool call, and which end of it to keep when it is
# too long. A path's filename is at the end, so trimming the front is what keeps
# it recognisable; a command says what it does at the front.
_TOOL_DETAIL: tuple[tuple[str, str], ...] = (
    ("command", "head"),
    ("file_path", "tail"),
    ("path", "tail"),
    ("pattern", "head"),
    ("url", "head"),
    ("prompt", "head"),
)
_DETAIL_WIDTH = 60


def summarize_tool(call: dict[str, Any]) -> str:
    """``Read(…/project/x.py)`` — the tool and the one argument worth showing."""
    name = call.get("name", "tool")
    arguments = call.get("input") or {}
    for key, keep in _TOOL_DETAIL:
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            detail = " ".join(value.split())
            if len(detail) > _DETAIL_WIDTH:
                detail = (
                    detail[: _DETAIL_WIDTH - 1] + "…"
                    if keep == "head"
                    else "…" + detail[-(_DETAIL_WIDTH - 1) :]
                )
            return f"{name}({detail})"
    return name


class TranscriptStore:
    """In-memory transcript mirror with an in-place edit operation.

    Duck-typed: the SDK probes for methods rather than using ``isinstance``,
    so only ``append`` and ``load`` are required.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[SessionStoreEntry]] = {}

    # --- SessionStore protocol -------------------------------------------

    async def append(self, key: SessionKey, entries: list[SessionStoreEntry]) -> None:
        self._sessions.setdefault(_key(key), []).extend(entries)

    async def load(self, key: SessionKey) -> list[SessionStoreEntry] | None:
        return self._sessions.get(_key(key)) or None

    # --- application layer ------------------------------------------------

    def entries(self, session_id: str) -> list[SessionStoreEntry]:
        return self._sessions.get(session_id, [])

    def messages(self, session_id: str) -> list[SessionStoreEntry]:
        """The user/assistant entries worth showing.

        Text or a tool call counts as visible. A line that is only a tool_result
        does not: it is the transcript's own bookkeeping, it is what pairs with
        a tool_use to keep the history valid, and showing it would double every
        tool call on screen. Keeping it unaddressable is also what stops an edit
        from cutting a tool_use away from its result.

        A local slash command's output arrives as a ``system`` entry rather than
        an assistant one, so filtering on role alone dropped it and the command
        looked like it had done nothing. ``isMeta`` lines are the opposite case:
        real entries the model is meant to read and a person is not.
        """
        return [
            e
            for e in self.entries(session_id)
            if not is_meta(e)
            and (
                is_command_output(e)
                or (
                    e.get("type") in ("user", "assistant")
                    and (text_of(e) or tool_calls_of(e))
                    and not is_tool_result(e)
                )
            )
        ]

    def rollback(self, session_id: str, length: int) -> None:
        """Discard entries written after ``length`` — undo a failed turn."""
        entries = self._sessions.get(session_id)
        if entries is not None and len(entries) > length:
            del entries[length:]

    def truncate(self, session_id: str, uuid: str) -> int:
        """Remove a message *and* everything after it; returns entries dropped.

        ``edit`` keeps the message and drops what follows. This drops the
        message too, so it can be sent again without appearing twice.
        """
        entries = self._sessions.get(session_id)
        if not entries:
            return -1
        index = next((i for i, e in enumerate(entries) if e.get("uuid") == uuid), None)
        if index is None:
            return -1
        dropped = len(entries) - index
        del entries[index:]
        return dropped

    def edit(self, session_id: str, uuid: str, new_text: str) -> int:
        """Rewrite one message and drop everything after it.

        Returns the number of following entries discarded, or -1 if not found.
        The content shape is preserved: user entries hold a plain string,
        assistant entries a list of blocks.
        """
        entries = self._sessions.get(session_id)
        if not entries:
            return -1
        index = next((i for i, e in enumerate(entries) if e.get("uuid") == uuid), None)
        if index is None:
            return -1

        message = _message(entries[index])
        message["content"] = (
            new_text if isinstance(message.get("content"), str)
            else [{"type": "text", "text": new_text}]
        )
        dropped = len(entries) - (index + 1)
        del entries[index + 1 :]
        return dropped

    # --- durability --------------------------------------------------------
    #
    # The transcript is the whole of the model-visible state — ``load()`` is
    # handed to the CLI verbatim — so dumping these entries dumps everything
    # needed to bring a conversation back. Entries are the plain dicts the CLI
    # emitted, so this is already JSON.

    def dump(self) -> dict[str, list[SessionStoreEntry]]:
        return {session: list(entries) for session, entries in self._sessions.items()}

    def restore(self, data: dict[str, list[SessionStoreEntry]]) -> None:
        self._sessions = {session: list(entries) for session, entries in data.items()}

"""Builders for transcript entries shaped like the ones the CLI actually emits.

User entries carry ``content`` as a plain string; assistant entries carry a list
of content blocks. Editing must preserve that distinction, so the tests use the
real shapes rather than a simplified stand-in.
"""

import asyncio

import pytest

from inshirah.core import usage
from inshirah.core.store import TranscriptStore

SESSION = "11111111-2222-3333-4444-555555555555"


@pytest.fixture(autouse=True)
def usage_elsewhere(tmp_path_factory, monkeypatch):
    """Point the usage counters at a scratch directory, for every test.

    Autouse and unconditional because the counters hang off ordinary engine
    methods — editing a message counts an edit — so any test that exercises the
    engine would otherwise write to the developer's real ``~/.inshirah``, and
    the first symptom would be a number in ``--stats`` that no one could
    account for.

    Deliberately *not* under the test's own ``tmp_path``: several tests assert
    that a directory they were given is untouched, and a counter appearing in
    it would make them fail for a reason that has nothing to do with what they
    are checking.
    """
    monkeypatch.setattr(usage, "DIRECTORY", tmp_path_factory.mktemp("usage"))


def user_entry(uuid: str, text: str) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": SESSION,
        "message": {"role": "user", "content": text},
    }


def meta_entry(uuid: str, text: str) -> dict:
    """A line the CLI writes for the model's benefit, not for a reader.

    Marked ``isMeta``; the caveat that precedes every local slash command is one.
    """
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": SESSION,
        "isMeta": True,
        "message": {"role": "user", "content": text},
    }


def command_entry(uuid: str, name: str, arguments: str = "") -> dict:
    """How the CLI records the slash command you typed."""
    return {
        "type": "user",
        "uuid": uuid,
        "sessionId": SESSION,
        "message": {
            "role": "user",
            "content": (
                f"<command-name>{name}</command-name>\n"
                f"            <command-message>{name.lstrip('/')}</command-message>\n"
                f"            <command-args>{arguments}</command-args>"
            ),
        },
    }


def command_output_entry(uuid: str, text: str) -> dict:
    """How the CLI records what a local slash command printed."""
    return {
        "type": "system",
        "subtype": "local_command",
        "uuid": uuid,
        "sessionId": SESSION,
        "isMeta": False,
        "level": "info",
        "content": f"<local-command-stdout>{text}</local-command-stdout>",
    }


def assistant_entry(uuid: str, text: str, message_id: str | None = None) -> dict:
    return {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": SESSION,
        "message": {
            "role": "assistant",
            "id": message_id or f"msg_{uuid}",
            "content": [{"type": "text", "text": text}],
        },
    }


def noise_entry(uuid: str) -> dict:
    """A non-message transcript line, e.g. a queue operation."""
    return {"type": "queue-operation", "uuid": uuid, "sessionId": SESSION}


@pytest.fixture
def key() -> dict:
    return {"project_key": "proj", "session_id": SESSION}


@pytest.fixture
def store(key) -> TranscriptStore:
    """A store holding a two-exchange conversation plus a non-message line."""
    s = TranscriptStore()
    asyncio.run(
        s.append(
            key,
            [
                user_entry("u1", "Invent a codename."),
                assistant_entry("a1", "Falcon"),
                noise_entry("n1"),
                user_entry("u2", "Recap please."),
                assistant_entry("a2", "The codename is Falcon."),
            ],
        )
    )
    return s


def context_of(store: TranscriptStore, key: dict) -> list[tuple[str, str]]:
    """Exactly what the model would be given: (role, text) in order."""
    from inshirah.core.store import text_of

    entries = asyncio.run(store.load(key)) or []
    return [(e["type"], text_of(e)) for e in entries if e.get("type") in ("user", "assistant")]

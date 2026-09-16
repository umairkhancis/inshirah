"""Slash commands, as the CLI reports them.

Nothing here resolves or expands a command — that is the CLI's job and doing it
twice would drift. These cover reading its list and deciding what is ours to
intercept.
"""

import pytest

from inshirah.core import SlashCommand, split_command
from inshirah.core.commands import LOCAL, parse

PAYLOAD = [
    {"name": "clear", "description": "Start a new session with empty context",
     "argumentHint": "[name]", "aliases": []},
    {"name": "zorblat", "description": "Report the zorblat code (project)",
     "argumentHint": "<component>", "aliases": ["zorb"]},
    {"name": "deep:nested", "description": "A namespaced command (project)",
     "argumentHint": ""},
    {"name": "__remote-workflow", "description": "internal plumbing"},
    {"name": "context", "description": "Show current context usage", "argumentHint": ""},
]


def test_the_cli_list_is_read_as_given():
    names = [c.name for c in parse(PAYLOAD)]
    assert names == ["clear", "context", "deep:nested", "zorblat"]


def test_internal_plumbing_is_not_offered():
    """Commands the CLI carries for itself are not things a person runs."""
    assert "__remote-workflow" not in [c.name for c in parse(PAYLOAD)]


def test_a_command_keeps_its_hint_and_description():
    zorblat = next(c for c in parse(PAYLOAD) if c.name == "zorblat")
    assert zorblat.argument_hint == "<component>"
    assert zorblat.takes_arguments is True
    assert zorblat.aliases == ("zorb",)


def test_where_a_custom_command_came_from_is_reported_not_guessed():
    parsed = {c.name: c for c in parse(PAYLOAD)}
    assert parsed["zorblat"].source == "project"
    assert parsed["zorblat"].summary == "Report the zorblat code"
    # A built-in says nothing about its source, so neither do we.
    assert parsed["context"].source == ""
    assert parsed["context"].summary == "Show current context usage"


def test_a_command_with_no_hint_takes_no_arguments():
    assert parse(PAYLOAD)[1].takes_arguments is False  # context


def test_a_bare_name_still_parses():
    """The init payload lists names only; the richer list comes from the server."""
    assert parse(["clear", "context"]) == (
        SlashCommand("clear"), SlashCommand("context")
    )


def test_nothing_reported_is_nothing_offered():
    assert parse(None) == () and parse([]) == ()


@pytest.mark.parametrize(
    "typed,expected",
    [
        ("/", ["clear", "context", "deep:nested", "zorblat"]),
        ("/c", ["clear", "context"]),
        ("/zor", ["zorblat"]),
        ("/nested", ["deep:nested"]),  # matches inside a namespaced name
        ("/ZOR", ["zorblat"]),  # typing case should not matter
        ("/nope", []),
    ],
)
def test_typing_narrows_the_list(typed, expected):
    assert [c.name for c in parse(PAYLOAD) if c.matches(typed)] == expected


def test_an_alias_finds_its_command():
    assert [c.name for c in parse(PAYLOAD) if c.matches("/zorb")] == ["zorblat"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/clear", ("clear", "")),
        ("/clear  release notes  ", ("clear", "release notes")),
        ("/deep:nested", ("deep:nested", "")),
        ("what is an index?", ("", "what is an index?")),
        ("!ls", ("", "!ls")),
    ],
)
def test_a_command_is_split_from_its_arguments(text, expected):
    assert split_command(text) == expected


def test_only_the_two_surface_commands_are_intercepted():
    """Everything else must reach the CLI, or it stops behaving like Claude Code."""
    assert LOCAL == ("clear", "rename")
    parsed = {c.name: c for c in parse(PAYLOAD)}
    assert parsed["clear"].local is True
    assert parsed["context"].local is False
    assert parsed["zorblat"].local is False


# --- what a slash command leaves in the transcript -----------------------
#
# The CLI records a local command in three pieces: a caveat for the model, the
# command you typed, and what it printed. Only two of those are for a reader,
# and the shapes are the CLI's, so these use the real ones.

from conftest import (  # noqa: E402
    SESSION, assistant_entry, command_entry, command_output_entry, meta_entry, user_entry,
)

from inshirah.core.store import TranscriptStore, presentation  # noqa: E402


def transcript(*entries):
    import asyncio

    store = TranscriptStore()
    asyncio.run(store.append({"project_key": "p", "session_id": SESSION}, list(entries)))
    return store


def test_the_command_you_typed_is_shown_as_you_typed_it():
    assert presentation(command_entry("c1", "/model")) == ("user", "/model")


def test_a_command_keeps_its_arguments():
    assert presentation(command_entry("c1", "/clear", "release notes")) == (
        "user", "/clear release notes"
    )


def test_command_output_is_its_own_kind_of_message():
    """Not the model talking — the CLI printing."""
    assert presentation(command_output_entry("c2", "Current model: Opus 5")) == (
        "command", "Current model: Opus 5"
    )


def test_an_ordinary_message_is_untouched():
    assert presentation(user_entry("u1", "what is an index?")) == (
        "user", "what is an index?"
    )


def test_the_caveat_the_cli_writes_for_the_model_is_not_shown():
    """Reported: it appeared in the transcript as a message of its own."""
    store = transcript(
        meta_entry("m1", "<local-command-caveat>Caveat: …</local-command-caveat>"),
        command_entry("c1", "/model"),
        command_output_entry("c2", "Current model: Opus 5"),
    )
    assert [e.get("uuid") for e in store.messages(SESSION)] == ["c1", "c2"]


def test_command_output_is_no_longer_dropped():
    """Reported: /model appeared to do nothing, because its output is a
    ``system`` entry and only user and assistant entries were kept."""
    store = transcript(command_entry("c1", "/model"), command_output_entry("c2", "Opus 5"))
    assert [presentation(e) for e in store.messages(SESSION)] == [
        ("user", "/model"),
        ("command", "Opus 5"),
    ]


def test_ordinary_messages_still_survive_the_filter():
    store = transcript(user_entry("u1", "hello"), assistant_entry("a1", "hi"))
    assert [e.get("uuid") for e in store.messages(SESSION)] == ["u1", "a1"]

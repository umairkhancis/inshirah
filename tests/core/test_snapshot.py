"""The read model — what a client renders from.

Every client otherwise re-derives the same facts from the object graph. The TUI
already did that for reply counts and the breadcrumb, and a second client would
have made it a third opinion on what a thread is called.
"""

import asyncio

import pytest
from conftest import SESSION, assistant_entry, user_entry

from inshirah.core import Conversation


@pytest.fixture
def tree(key):
    c = Conversation()
    c.session_id = SESSION
    asyncio.run(
        c.store.append(
            key,
            [
                user_entry("u1", "What is an index?"),
                assistant_entry("a1", "An index speeds up lookups."),
            ],
        )
    )
    c._sync()
    return c


def test_snapshot_carries_the_turns_and_their_handles(tree):
    snapshot = tree.snapshot()
    assert [(t["role"], t["text"], t["uuid"]) for t in snapshot["turns"]] == [
        ("user", "What is an index?", "u1"),
        ("assistant", "An index speeds up lookups.", "a1"),
    ]


def test_snapshot_points_at_the_thread_hanging_off_a_message(tree):
    thread = tree.thread_for("a1")
    turn = next(t for t in tree.snapshot()["turns"] if t["uuid"] == "a1")
    assert turn["thread_id"] == thread.id
    assert next(t for t in tree.snapshot()["turns"] if t["uuid"] == "u1")["thread_id"] is None


def test_snapshot_reports_an_unstarted_thread(tree):
    snapshot = tree.thread_for("a1").snapshot()
    assert snapshot["started"] is False and snapshot["session_id"] is None
    assert snapshot["turns"] == []


def test_snapshot_never_claims_more_inherited_than_it_has(tree):
    """The unstarted-thread bug: inherited is a promise, turns are the fact."""
    thread = tree.thread_for("a1")
    assert thread.inherited == 2
    assert thread.snapshot()["inherited"] == 0


def test_tree_snapshot_covers_every_thread(tree):
    tree.thread_for("a1").thread_for("x")
    ids = {t["id"] for t in tree.tree_snapshot()["threads"]}
    assert len(ids) == 3


def test_breadcrumb_is_the_path_down_to_the_thread(tree):
    deep = tree.thread_for("a1").thread_for("x")
    assert deep.breadcrumb()[0] == "main"
    assert len(deep.breadcrumb()) == 3


def test_a_thread_is_named_by_the_question_not_the_reply(tree):
    """Hanging a thread off "An index speeds up lookups." names it for the ask."""
    assert tree.thread_for("a1").title() == "What is an index?"


def test_title_width_only_trims(tree):
    assert tree.thread_for("a1").title(width=7) == "What is"


def test_render_export_returns_markdown_without_writing(tree, tmp_path):
    body = tree.render_export()
    assert "## Context sent to the model" in body
    assert "An index speeds up lookups." in body
    assert list(tmp_path.iterdir()) == []  # nothing touched the filesystem


def test_export_writes_what_render_produced(tree, tmp_path):
    path = tree.export(str(tmp_path))
    assert path.read_text() == (tmp_path / "latest.md").read_text()
    assert "## Context sent to the model" in path.read_text()

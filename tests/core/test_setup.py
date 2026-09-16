"""The first failure a new user hits, and whether it tells them what to do.

Inshirah is a Python package that drives a Node CLI. Someone who installed it
with `uvx inshirah` has no reason to know that, so "Claude Code not found" is a
dead end unless it comes with the two commands that fix it.
"""

from claude_agent_sdk import CLINotFoundError

from inshirah.core import explain_setup_failure
from inshirah.core import setup


def test_a_missing_cli_is_answered_with_the_install():
    fix = explain_setup_failure(CLINotFoundError())
    assert setup.CLI_PACKAGE in fix
    assert "npm install -g" in fix


def test_the_install_also_says_to_sign_in():
    """Installing the CLI is half of it; a fresh install has no session."""
    assert "claude" in explain_setup_failure(CLINotFoundError())
    assert "sign in" in explain_setup_failure(CLINotFoundError())


def test_it_says_inshirah_wants_no_key_of_its_own():
    """The trust claim belongs where a new user is being asked to set things
    up, not only in a README they did not read."""
    assert "never asks for a key of its own" in setup.MISSING


def test_an_expired_login_is_told_apart_from_a_missing_install():
    fix = explain_setup_failure(RuntimeError("API Error: 401 authentication_error"))
    assert "not signed in" in fix
    assert "npm install" not in fix  # it is installed; that is not the problem


def test_a_login_prompt_from_the_cli_is_recognised():
    assert explain_setup_failure(RuntimeError("Please run /login")) is not None


def test_an_ordinary_failure_is_left_alone():
    """Returning None means "not a setup problem" — the caller then shows the
    real error instead of a guess dressed up as instructions."""
    assert explain_setup_failure(ValueError("the model refused")) is None


def test_it_never_raises_on_an_odd_exception():
    class Odd(Exception):
        def __str__(self):
            return "\U0001f600"

    assert explain_setup_failure(Odd()) is None


# --- reaching the Claude Code that came with the install -------------------
#
# Found on a clean machine: `claude` is not on PATH after `uv tool install
# inshirah`, because the bundled copy lives under site-packages. Advice that
# names a command the user does not have is a dead end, not advice.


def test_the_bundled_copy_is_preferred_over_one_on_the_path(monkeypatch, tmp_path):
    """The SDK runs the bundled one, so the sign-in must happen in that one."""
    bundled = tmp_path / "_bundled"
    bundled.mkdir()
    (bundled / "claude").write_text("#!/bin/sh\n")
    monkeypatch.setattr(setup.claude_agent_sdk, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/claude")
    assert setup.claude_binary() == str(bundled / "claude")


def test_the_path_is_the_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.claude_agent_sdk, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/claude")
    assert setup.claude_binary() == "/usr/bin/claude"


def test_no_claude_anywhere_is_none_rather_than_a_guess(monkeypatch, tmp_path):
    monkeypatch.setattr(setup.claude_agent_sdk, "__file__", str(tmp_path / "__init__.py"))
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    assert setup.claude_binary() is None


def test_the_signed_out_advice_names_a_command_the_user_actually_has():
    """`claude` is exactly what they do not have; `inshirah` is what they ran."""
    assert "inshirah --login" in setup.SIGNED_OUT

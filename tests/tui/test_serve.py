"""Serving the TUI in a browser.

This is the same app streamed over a websocket, not a separate web client — so
what is worth testing is the command each browser session runs, and the warning
for the case that turns a local tool into a remote shell for anyone on the
network.
"""

from argparse import Namespace

import pytest

from inshirah.tui import serve as serve_module
from inshirah.tui.__main__ import parse_args


def args(*argv) -> Namespace:
    return parse_args(list(argv))


def command(*argv, project="/proj") -> str:
    return serve_module.tui_command(args(*argv), project)


def test_the_served_session_is_pinned_to_the_project():
    """A served session starts wherever the server did, and the directory is
    the whole of which CLAUDE.md, skills and MCP servers load."""
    assert "--cwd /proj" in command(project="/proj")


def test_the_served_session_runs_the_tui():
    assert "-m inshirah.tui" in command()


def test_permission_narrowing_is_carried_through():
    """Serving must not quietly widen what the agent may do."""
    assert "--permission-mode plan" in command("--permission-mode", "plan")


def test_allow_and_deny_are_carried_through():
    built = command("--allow", "Read", "Grep", "--deny", "Bash")
    assert "--allow Read Grep" in built and "--deny Bash" in built


def test_extra_directories_are_carried_through():
    assert "--add-dir /other" in command("--add-dir", "/other")


def test_arguments_are_quoted_for_the_shell():
    """The command is a string that gets re-parsed, so a spaced path must survive."""
    assert "'/a path/proj'" in command(project="/a path/proj")


def test_serving_is_off_unless_asked():
    assert args().serve is False


def test_serving_defaults_to_loopback():
    """The app is Claude Code plus !command, with no authentication at all."""
    assert args().host == "127.0.0.1"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_are_not_warned_about(host):
    assert host in serve_module.LOOPBACK


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_exposing_it_beyond_loopback_is_warned_about(host):
    assert host not in serve_module.LOOPBACK


def test_the_warning_says_what_is_actually_at_risk():
    warning = serve_module.EXPOSURE_WARNING.format(host="0.0.0.0")
    assert "run commands on this machine" in warning
    assert "no login" in warning.lower()


def test_a_missing_dependency_explains_how_to_fix_it(monkeypatch, capsys):
    """--serve is an extra, so the failure must name the install, not traceback."""
    monkeypatch.setitem(__import__("sys").modules, "textual_serve", None)
    assert serve_module.serve(args("--serve"), "/proj") == 1
    assert "textual-serve" in capsys.readouterr().out


# --- serving somewhere public --------------------------------------------
#
# A warning is enough when a person types the command and reads the output. A
# deployment has no one reading, so beyond loopback this refuses to start unless
# the environment says the exposure is deliberate.


def test_a_public_host_is_refused_rather_than_warned(monkeypatch, capsys):
    monkeypatch.delenv(serve_module.PUBLIC_GATE, raising=False)
    assert serve_module.serve(args("--serve", "--host", "0.0.0.0"), "/proj") == 2
    printed = capsys.readouterr().out
    assert "Refusing to serve" in printed
    assert serve_module.PUBLIC_GATE in printed  # and it says how to mean it


def test_the_refusal_explains_what_is_at_risk(monkeypatch, capsys):
    monkeypatch.delenv(serve_module.PUBLIC_GATE, raising=False)
    serve_module.serve(args("--serve", "--host", "0.0.0.0"), "/proj")
    printed = capsys.readouterr().out
    assert "no login" in printed
    assert "remote shell" in printed


def test_loopback_never_needs_the_gate(monkeypatch):
    """The default path must not grow a new hoop; it is the same trust boundary
    as running the TUI yourself."""
    monkeypatch.delenv(serve_module.PUBLIC_GATE, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "textual_serve", None)
    # Falls through to the missing-dependency path, not the refusal.
    assert serve_module.serve(args("--serve"), "/proj") == 1


def test_acknowledging_the_exposure_lets_it_through(monkeypatch, capsys):
    monkeypatch.setenv(serve_module.PUBLIC_GATE, "1")
    monkeypatch.setitem(__import__("sys").modules, "textual_serve", None)
    assert serve_module.serve(args("--serve", "--host", "0.0.0.0"), "/proj") == 1
    printed = capsys.readouterr().out
    assert "Refusing" not in printed
    assert "WARNING" in printed  # still says so, for the logs


def test_the_port_comes_from_the_environment_when_a_host_assigns_one(monkeypatch):
    """Vercel, Fly and Cloud Run all hand the port over in $PORT."""
    monkeypatch.setenv("PORT", "8080")
    assert args("--serve").port == 8080


def test_the_port_still_defaults_without_one(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert args("--serve").port == 8000


def test_an_explicit_port_beats_the_environment(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    assert args("--serve", "--port", "9000").port == 9000


# --- opening the browser --------------------------------------------------
#
# `--serve` is one of the two front doors onto a local install, so it should
# land the user in the app rather than in a URL they have to copy.


def test_the_browser_is_opened_by_default():
    assert args("--serve").open_browser is True


def test_opening_can_be_declined():
    assert args("--serve", "--no-open").open_browser is False


def test_opening_waits_for_the_server_to_be_listening():
    """Server.serve() blocks and offers no started-callback, so opening
    immediately would land on connection-refused."""
    opened = []
    serve_module.open_when_ready("http://127.0.0.1:8000", opened.append, delay=0.01)
    import time

    time.sleep(0.2)
    assert opened == ["http://127.0.0.1:8000"]

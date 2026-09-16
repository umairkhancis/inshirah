"""The flags, and what they turn into.

They only ever narrow the harness — there is no flag that turns the agent off or
swaps it out. Nothing here reconfigures Claude Code either: a project's own
settings, CLAUDE.md, .mcp.json and plugins are loaded by the CLI whether or not
Inshirah mentions them.
"""

import pytest

from inshirah.tui.__main__ import harness_from, parse_args


def harness(*argv):
    return harness_from(parse_args(list(argv)))


def test_the_default_is_the_whole_harness_on_auto():
    h = harness()
    assert h.permission_mode == "auto"
    assert h.options()["system_prompt"] == {"type": "preset", "preset": "claude_code"}


def test_permission_mode_can_be_tightened():
    assert harness("--permission-mode", "plan").permission_mode == "plan"


def test_an_unknown_permission_mode_is_rejected_at_the_command_line():
    with pytest.raises(SystemExit):
        parse_args(["--permission-mode", "yolo"])


def test_tools_can_be_pre_approved():
    assert harness("--allow", "Read", "Grep").options()["allowed_tools"] == ["Read", "Grep"]


def test_tools_can_be_removed_entirely():
    assert harness("--deny", "Bash").options()["disallowed_tools"] == ["Bash"]


def test_the_project_directory_decides_which_memory_loads(tmp_path):
    assert harness("--cwd", str(tmp_path)).options()["cwd"] == str(tmp_path)


def test_extra_directories_are_passed_through(tmp_path):
    assert harness("--add-dir", str(tmp_path)).options()["add_dirs"] == [str(tmp_path)]


def test_the_project_defaults_to_where_it_was_launched(tmp_path, monkeypatch):
    """`cd my-project && inshirah` must work the way `claude` does."""
    monkeypatch.chdir(tmp_path)
    assert harness().project == str(tmp_path)


def test_check_is_off_unless_asked():
    assert parse_args([]).check is False


def test_check_can_be_asked_for():
    assert parse_args(["--check"]).check is True


def test_an_installed_command_points_at_main():
    """The console script is what makes this usable outside its own repo."""
    import tomllib
    import pathlib

    pyproject = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
    assert pyproject["project"]["scripts"]["inshirah"] == "inshirah.tui.__main__:main"


def test_the_tui_dependency_is_not_optional():
    """The only console script is the TUI, so an install without textual ships
    a command that cannot start. The core/client seam is enforced by imports —
    inshirah.core pulls in no textual — not by making the front end optional."""
    import tomllib
    import pathlib

    project = tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]
    assert any(d.startswith("textual") for d in project["dependencies"])
    assert "tui" not in project.get("optional-dependencies", {})


def test_importing_the_core_does_not_pull_in_a_front_end():
    """What the seam actually guarantees, packaging aside."""
    import subprocess
    import sys

    probe = "import sys, inshirah.core; sys.exit('textual' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", probe]).returncode == 0


# --- being installable by a stranger -------------------------------------
#
# Everything above is about the app. These are about the package: what someone
# who has never seen this repo gets when they type `uvx inshirah`.


def project_metadata() -> dict:
    import tomllib
    import pathlib

    return tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]


def test_the_version_is_single_sourced_from_the_package():
    """A wheel whose --version disagrees with its metadata is a bug report
    nobody can act on, so the version has exactly one home."""
    metadata = project_metadata()
    assert "version" in metadata["dynamic"]
    assert "version" not in metadata


def test_the_version_is_reportable(capsys):
    from inshirah import __version__

    with pytest.raises(SystemExit):
        parse_args(["--version"])
    assert __version__ in capsys.readouterr().out


def test_the_package_carries_the_page_it_will_be_published_with():
    """PyPI renders the readme, so until there is a landing page it *is* the
    landing page — a package without one arrives blank."""
    import pathlib

    assert project_metadata()["readme"] == "README.md"
    assert pathlib.Path("README.md").is_file()


def test_the_package_is_licensed():
    import pathlib

    assert project_metadata()["license"] == "MIT"
    assert pathlib.Path("LICENSE").is_file()


def test_the_browser_front_door_is_not_an_optional_extra():
    """Both ways of running it are advertised, so both have to work after one
    install; an extra is a footnote nobody reads until --serve fails."""
    assert any(d.startswith("textual-serve") for d in project_metadata()["dependencies"])


def test_the_old_extra_still_resolves():
    """`pip install inshirah[web]` was the documented install; it must not
    start erroring at people reading an older page."""
    assert "web" in project_metadata()["optional-dependencies"]


def test_what_leaves_the_machine_can_be_asked_without_starting_anything():
    assert parse_args(["--privacy"]).privacy is True
    assert parse_args([]).privacy is False


def test_signing_in_is_reachable_from_the_command_that_was_installed():
    assert parse_args(["--login"]).login is True
    assert parse_args([]).login is False


def test_signing_in_runs_the_binary_inshirah_would_run(monkeypatch, capsys):
    """Not `claude` from PATH — the bundled copy, which is the one the SDK
    starts and the one that has to hold the session."""
    from inshirah.tui import __main__ as cli

    started = []
    monkeypatch.setattr(cli, "claude_binary", lambda: "/somewhere/_bundled/claude")
    monkeypatch.setattr(cli.subprocess, "call", lambda argv: started.append(argv) or 0)
    assert cli.login() == 0
    # `auth login`, not the bare REPL: one job, then it gets out of the way.
    assert started == [["/somewhere/_bundled/claude", "auth", "login"]]
    assert "/somewhere/_bundled/claude" in capsys.readouterr().out


def test_signing_in_with_nothing_to_sign_in_to_says_how_to_install(monkeypatch, capsys):
    from inshirah.tui import __main__ as cli

    monkeypatch.setattr(cli, "claude_binary", lambda: None)
    assert cli.login() == 1
    assert "npm install -g" in capsys.readouterr().out


def test_a_project_becomes_one_directory_name():
    from inshirah.tui.__main__ import project_slug

    assert project_slug("/home/u/code/proj") == "home-u-code-proj"


def test_a_windows_path_does_not_produce_an_illegal_directory_name():
    """`:` is legal in a Windows path and illegal in a Windows file name, so
    swapping separators alone yields a directory Windows refuses to create."""
    from inshirah.tui.__main__ import project_slug

    slug = project_slug("C:\\Users\\u\\code\\proj")
    assert slug == "C-Users-u-code-proj"
    assert ":" not in slug and "\\" not in slug


# --- the one command someone is asked to run -----------------------------
#
# The install instruction had an unstated prerequisite: `uv tool install` reads
# as one command, but uv is a separate tool most machines do not have, so the
# first thing a stranger met was `uv: command not found`. Whatever the readme
# tells people to run has to be the thing that actually exists.


def test_both_installers_ship():
    import pathlib

    assert pathlib.Path("scripts/install.sh").is_file()
    assert pathlib.Path("scripts/install.ps1").is_file()


def test_the_shell_installer_is_valid_posix_sh():
    import subprocess

    assert subprocess.run(["sh", "-n", "scripts/install.sh"]).returncode == 0


def test_the_installer_does_not_need_anything_installed_first():
    """Its whole purpose: uv, and therefore Python, are its job not the user's."""
    installer = __import__("pathlib").Path("scripts/install.sh").read_text()
    assert "astral.sh/uv/install.sh" in installer
    assert "uv tool install" in installer


def test_the_installer_never_asks_for_root():
    """Comments excluded — the file says the word while promising not to."""
    installer = __import__("pathlib").Path("scripts/install.sh").read_text()
    code = [ln for ln in installer.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("sudo" in ln for ln in code)


def test_the_readme_tells_people_to_run_the_installer_that_exists():
    """A readme naming a command nobody has is how this went wrong the first
    time, so the two are checked against each other."""
    readme = __import__("pathlib").Path("README.md").read_text()
    assert "install.sh | sh" in readme
    assert "install.ps1 | iex" in readme

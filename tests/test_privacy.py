"""The promise that there is no backend, held to by the test suite.

Inshirah asks people to run an AI surface over their own source code. The claim
that makes that safe — no account, no server, no telemetry — is worth exactly as
much as it is enforced, so this is the enforcement: the package may not import a
network client, and the statement it prints has to keep matching the code.
"""

import ast
import pathlib

from inshirah.core import privacy_report

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "inshirah"

# Anything that could open a socket of its own. `claude_agent_sdk` is absent by
# design: it starts the Claude Code process, which is the one thing here that is
# allowed to talk to a network, and it talks to the user's provider, not to us.
NETWORK_MODULES = {
    "http",
    "httpx",
    "requests",
    "socket",
    "ssl",
    "urllib",
    "aiohttp",
    "websockets",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc",
}


def imported_modules() -> dict[str, set[str]]:
    """Every top-level module name imported anywhere in the package."""
    found: dict[str, set[str]] = {}
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
        found[str(path.relative_to(PACKAGE))] = names
    return found


def test_the_package_imports_no_network_client():
    """The load-bearing test. If this ever fails, the README is lying."""
    offenders = {
        path: sorted(names & NETWORK_MODULES)
        for path, names in imported_modules().items()
        if names & NETWORK_MODULES
    }
    assert offenders == {}


def test_nothing_in_the_package_names_a_remote_host():
    """A URL in the source is the other shape this leak would take. Only the
    documented links are allowed, and they are documentation, not destinations."""
    # docs.google.com is the form ``share`` prefills. It is a destination, and
    # it is the one exception in this file, so it is worth saying why it is not
    # a hole: the package cannot reach it. Nothing here opens a connection to
    # that URL — it is handed to ``webbrowser``, and a person decides. If a
    # network client ever appears alongside it, the test above fails first.
    allowed = (
        "https://github.com/umairkhancis",
        "https://docs.google.com/forms/",
        "http://localhost",
        "http://127.0.0.1",
    )
    for path in PACKAGE.rglob("*.py"):
        for line in path.read_text().splitlines():
            for scheme in ("http://", "https://"):
                at = line.find(scheme)
                if at != -1 and not line[at:].startswith(allowed):
                    # f-strings that build a loopback URL from a flag
                    assert "{args.host}" in line or "{host}" in line, f"{path}: {line}"


def test_the_statement_names_where_conversations_actually_live():
    assert "/tmp/somewhere" in privacy_report("/tmp/somewhere")


def test_the_statement_expands_a_home_relative_path():
    """It is printed so a person can go and look at the directory."""
    assert "~" not in privacy_report("~/.inshirah/projects")


def test_the_statement_is_unambiguous_about_telemetry():
    report = privacy_report("~/.inshirah")
    assert "no telemetry" in report
    assert "no account" in report


def test_the_statement_says_whose_key_pays():
    """The adoption story is that it rides on the Claude Code they already
    have — which is also why there is nothing of ours to leak to."""
    report = privacy_report("~/.inshirah")
    assert "billed to you" in report
    assert "never sees a key of yours" in report


# --- working notes stay working notes -------------------------------------
#
# A second promise, of a different kind: the notes that drove this — the phase
# brief, the bug list, the design questions, the commercial thinking — are not
# documentation of the product and are not published. That is one line in
# .gitignore, which is exactly the kind of line that gets deleted by accident
# during a refactor, and the cost of noticing late is that it is already public.

NOT_PUBLISHED = (
    "docs/PROMPT.md",
    "docs/edit-in-place.md",
    "docs/design-decisions.md",
    "docs/commercialization.md",
    "docs/bug.md",
)


def test_the_working_notes_are_not_publishable():
    ignored = {
        line.strip()
        for line in (PACKAGE.parent / ".gitignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert set(NOT_PUBLISHED) <= ignored


def test_the_release_checklists_are_published():
    """docs/ is not wholesale private — only the thinking is. The Homebrew
    formula points at its checklist, so hiding it would leave a dangling
    reference in a file strangers read."""
    for published in ("docs/releasing.md", "docs/homebrew.md"):
        assert (PACKAGE.parent / published).is_file()

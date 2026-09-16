"""What Claude Code loaded, as the CLI reported it.

None of this is Inshirah's to implement — skills, agents, hooks, MCP servers and
project memory are resolved by Claude Code from the directory it was launched
in. What Inshirah owes the user is visibility: a skill that failed to parse and
an MCP server that died look exactly like ones that work, and a surface that
silently drops half a project's configuration is worse than one that never
claimed to support it.
"""

import pytest

from inshirah.core import Environment
from inshirah.core.environment import find_memory_files

INIT = {
    "cwd": "/work/project",
    "model": "claude-opus-5",
    "permissionMode": "auto",
    "agents": ["general-purpose", "scribe"],
    "skills": ["pangolin-facts", "dataviz"],
    "slash_commands": ["pangolin-facts"],
    "tools": ["Read", "Write", "Bash", "Skill"],
    "plugins": [{"name": "frontend-design", "path": "/p"}],
    "memory_paths": {"auto": "/home/u/.claude/projects/-work-project/memory/"},
    "mcp_servers": [
        {"name": "linear", "status": "connected"},
        {"name": "broken-one", "status": "failed"},
    ],
}


@pytest.fixture
def env() -> Environment:
    return Environment.from_init(INIT, claude_md=("/work/project/CLAUDE.md",))


def test_the_project_directory_is_reported(env):
    """This is what decides which CLAUDE.md and settings load."""
    assert env.cwd == "/work/project"


def test_project_skills_are_reported(env):
    assert "pangolin-facts" in env.skills


def test_project_agents_are_reported(env):
    assert "scribe" in env.agents


def test_the_project_memory_directory_is_reported(env):
    assert env.memory_paths == ("/home/u/.claude/projects/-work-project/memory/",)


def test_plugins_are_named_not_dumped(env):
    assert env.plugins == ("frontend-design",)


def test_mcp_servers_keep_their_status(env):
    assert dict(env.mcp_servers)["linear"] == "connected"


def test_a_server_that_did_not_start_is_singled_out(env):
    """Otherwise its tools just never appear and the agent looks unhelpful."""
    assert env.broken_mcp == ("broken-one",)


def test_a_healthy_project_reports_nothing_broken():
    env = Environment.from_init({**INIT, "mcp_servers": [{"name": "linear", "status": "connected"}]})
    assert env.broken_mcp == ()


def test_summary_counts_what_loaded(env):
    summary = env.summary()
    assert "4 tools" in summary and "2 skills" in summary and "2 agents" in summary


def test_summary_flags_a_broken_server(env):
    assert "1 mcp failed" in env.summary()


def test_the_report_names_every_abstraction(env):
    report = env.report()
    for expected in ("pangolin-facts", "scribe", "frontend-design", "linear", "broken-one", "memory"):
        assert expected in report


def test_the_report_warns_about_servers_that_did_not_start(env):
    assert "WARNING" in env.report() and "broken-one" in env.report()


def test_an_empty_project_does_not_crash_the_report():
    """A directory with no .claude at all is a perfectly ordinary project."""
    report = Environment.from_init({}).report()
    assert "skills: none" in report and "mcp servers: none" in report


def test_mcp_servers_given_as_bare_names_are_tolerated():
    env = Environment.from_init({"mcp_servers": ["oddly-shaped"]})
    assert env.mcp_servers == (("oddly-shaped", "unknown"),)


# --- CLAUDE.md is the one thing the CLI never reports ----------------------


def test_claude_md_is_not_in_the_init_payload(env):
    """The bug this guards: memory_paths is the auto-memory directory only.

    Labelling that as "CLAUDE.md and project memory" implied a project's memory
    file was being listed when it never was — the file loaded, but --check gave
    no sign of it, which looks exactly like it being ignored.
    """
    assert "CLAUDE.md" not in str(INIT)


def test_a_project_claude_md_is_found(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("project memory")
    assert find_memory_files(str(tmp_path)) == (str(tmp_path / "CLAUDE.md"),)


def test_a_local_override_is_found_too(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("shared")
    (tmp_path / "CLAUDE.local.md").write_text("mine")
    assert len(find_memory_files(str(tmp_path))) == 2


def test_memory_is_inherited_from_a_parent_directory(tmp_path):
    """A package inside a monorepo gets the repository's memory as well."""
    (tmp_path / "CLAUDE.md").write_text("repo")
    package = tmp_path / "packages" / "api"
    package.mkdir(parents=True)
    (package / "CLAUDE.md").write_text("package")

    found = find_memory_files(str(package))
    assert found.index(str(tmp_path / "CLAUDE.md")) < found.index(str(package / "CLAUDE.md"))


def test_a_project_with_no_memory_reports_none(tmp_path):
    assert find_memory_files(str(tmp_path)) == ()


def test_the_report_lists_the_memory_file_it_found(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x")
    report = Environment.from_init({**INIT, "cwd": str(tmp_path)}).report()
    assert str(tmp_path / "CLAUDE.md") in report


def test_the_report_separates_memory_files_from_the_memory_directory(tmp_path):
    report = Environment.from_init(INIT, claude_md=("/p/CLAUDE.md",)).report()
    assert "CLAUDE.md (found on disk" in report
    assert "project memory directory" in report


def test_the_summary_counts_memory_files(tmp_path):
    env = Environment.from_init(INIT, claude_md=("/p/CLAUDE.md",))
    assert "1 CLAUDE.md" in env.summary()


def test_no_memory_file_is_visible_at_a_glance():
    """The common surprise: working in a project that has none."""
    assert "0 CLAUDE.md" in Environment.from_init(INIT, claude_md=()).summary()


# --- probing, and what it is allowed to call healthy ----------------------
#
# Found on a clean Ubuntu box with no Claude Code login: `--check` printed a
# full, healthy report — skills, agents, tools, the lot — on a machine that
# could not send a single message. `init` is the CLI describing the directory,
# and it arrives before anything has been authenticated, so returning at `init`
# reports "fine" to exactly the user who is about to hit a wall.


class FakeClient:
    """Enough of ClaudeSDKClient to run one turn's worth of messages."""

    def __init__(self, messages):
        self.messages = messages
        self.asked = None

    def __call__(self, options=None):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        self.asked = prompt

    async def receive_response(self):
        for message in self.messages:
            yield message


class FakeResult:
    """A ResultMessage-shaped object; probe only reads these three fields."""

    def __init__(self, is_error, errors=None, result=None):
        self.is_error = is_error
        self.errors = errors
        self.result = result


def init_message():
    from claude_agent_sdk import SystemMessage

    return SystemMessage(subtype="init", data=INIT)


def probe_with(monkeypatch, messages):
    import asyncio

    from inshirah.core import Harness, probe
    from inshirah.core import environment as module

    fake = FakeClient(messages)
    monkeypatch.setattr(module, "ClaudeSDKClient", fake)
    monkeypatch.setattr(module, "ResultMessage", FakeResult)
    return asyncio.run(probe(Harness(), timeout=5))


def test_a_finished_turn_reports_what_loaded(monkeypatch):
    loaded = probe_with(monkeypatch, [init_message(), FakeResult(is_error=False)])
    assert loaded.skills == ("pangolin-facts", "dataviz")


def test_a_signed_out_machine_is_not_reported_as_healthy(monkeypatch):
    """The real text from a machine that has never run `claude`."""
    from inshirah.core import SendFailed

    with pytest.raises(SendFailed, match="Not logged in"):
        probe_with(
            monkeypatch,
            [init_message(), FakeResult(is_error=True, result="Not logged in · Please run /login")],
        )


def test_the_failure_is_one_the_setup_advice_recognises(monkeypatch):
    """--check turns this into instructions, so the two have to agree."""
    from inshirah.core import SendFailed, explain_setup_failure

    try:
        probe_with(
            monkeypatch,
            [init_message(), FakeResult(is_error=True, result="Not logged in · Please run /login")],
        )
    except SendFailed as exc:
        assert explain_setup_failure(exc) is not None
    else:
        pytest.fail("a failed turn must raise")


def test_a_turn_that_never_said_what_loaded_is_an_error(monkeypatch):
    with pytest.raises(RuntimeError, match="before reporting"):
        probe_with(monkeypatch, [FakeResult(is_error=False)])


def test_probing_costs_a_turn_and_says_so_little_as_possible(monkeypatch):
    """It is charged to the user, so the prompt stays a syllable."""
    import asyncio

    from inshirah.core import Harness, probe
    from inshirah.core import environment as module

    fake = FakeClient([init_message(), FakeResult(is_error=False)])
    monkeypatch.setattr(module, "ClaudeSDKClient", fake)
    monkeypatch.setattr(module, "ResultMessage", FakeResult)
    asyncio.run(probe(Harness(), timeout=5))
    assert fake.asked == "hi"

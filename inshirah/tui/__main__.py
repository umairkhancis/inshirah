"""``python -m inshirah.tui`` — the terminal client, and its flags.

Claude Code runs underneath with everything on by default. These flags only
*narrow* that: they are how you dial the agent down for a session, never how you
reconfigure it. Anything Claude Code already reads — ``.claude/settings.json``,
CLAUDE.md, ``.mcp.json``, plugins, skills — is picked up without being mentioned
here, because Inshirah does not reimplement any of it.
"""

import argparse
import asyncio
import os
import pathlib
import subprocess
import sys

from inshirah import __version__
from inshirah.core import (
    PERMISSION_MODES,
    FileStorage,
    Harness,
    claude_binary,
    explain_setup_failure,
    privacy_report,
    probe,
    share,
    usage,
)
from inshirah.core.setup import MISSING

from .app import InshirahApp
from .serve import PUBLIC_GATE, serve

# 8000 unless the environment picked one; named so --help and the flag agree.
DEFAULT_PORT = 8000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="inshirah",
        description="A thoughtful surface over Claude Code: edit any message in "
        "place, branch a thread off any message.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"inshirah {__version__}",
    )
    parser.add_argument(
        "--permission-mode",
        default="auto",
        choices=PERMISSION_MODES,
        help="how much the agent may do unprompted (default: auto). Anything "
        "that still needs asking is asked in the TUI.",
    )
    parser.add_argument(
        "--allow",
        metavar="TOOL",
        nargs="+",
        default=[],
        help="tools to auto-approve without ever prompting, e.g. --allow Read Grep",
    )
    parser.add_argument(
        "--deny",
        metavar="TOOL",
        nargs="+",
        default=[],
        help="tools to remove entirely, e.g. --deny Bash. Stronger than --allow: "
        "a denied tool is not offered to the model at all.",
    )
    parser.add_argument(
        "--cwd",
        metavar="DIR",
        default=None,
        help="the project to work in (default: the current directory). This is "
        "what decides which CLAUDE.md and settings load.",
    )
    parser.add_argument(
        "--add-dir",
        metavar="DIR",
        nargs="+",
        default=[],
        help="extra directories the agent may reach outside the project",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="use it in a browser instead of the terminal. Same app, same "
        "machine, served on localhost — not a hosted service and not a separate "
        "web client. Each browser session gets its own process and its own "
        "conversation.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to serve on (default: 127.0.0.1). Anything other than "
        "loopback exposes an agent with shell access to this machine, "
        f"unauthenticated, and is refused unless ${PUBLIC_GATE} is set.",
    )
    parser.add_argument(
        "--port",
        type=int,
        # $PORT is the convention for "the port was chosen for you"; honouring
        # it costs nothing and means the flag is not the only way to move off
        # 8000 when something else already has it.
        default=int(os.environ.get("PORT") or DEFAULT_PORT),
        help=f"port to serve on (default: $PORT, else {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        help="do not open a browser window; just print the URL",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="sign in to Claude Code, using the copy Inshirah runs. Needed once "
        "per machine; the sign-in is Anthropic's and Inshirah never sees it.",
    )
    parser.add_argument(
        "--privacy",
        action="store_true",
        help="print what leaves this machine, and where conversations are "
        "kept, then exit. Free: it asks nothing and starts nothing.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="print what this copy of Inshirah has counted — sessions, edits, "
        "threads — and offer to send those numbers to the project through your "
        "own browser, then exit. Nothing is sent unless you say so.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what this directory loads — CLAUDE.md and project memory, "
        "skills, agents, MCP servers, plugins, tools — then exit. Costs one "
        "short turn: the CLI does not say what it loaded until a turn starts.",
    )
    return parser.parse_args(argv)


def harness_from(args: argparse.Namespace) -> Harness:
    return Harness(
        permission_mode=args.permission_mode,
        allowed_tools=tuple(args.allow),
        disallowed_tools=tuple(args.deny),
        cwd=args.cwd,
        add_dirs=tuple(args.add_dir),
    )


CONVERSATIONS = pathlib.Path("~/.inshirah/projects")


def storage_for(project: str) -> FileStorage:
    """Where this project's conversations live.

    Scoped per project, the way Claude Code scopes its own sessions: a
    conversation is about a particular codebase, and offering another project's
    conversations in the rail would only ever be a mistake.
    """
    return FileStorage(CONVERSATIONS / project_slug(project))


def project_slug(project: str) -> str:
    """A project path flattened into one directory name.

    Both separators, not just this platform's: a Windows path can arrive with
    either. The drive letter's colon has to go too — it is legal in a path on
    Windows and illegal in a file *name* there, so swapping separators alone
    produces a directory that cannot be created on the platform that produced
    the path.
    """
    flattened = project.replace("\\", "/").strip("/").replace("/", "-")
    return flattened.replace(":", "")


def login() -> int:
    """``--login`` — hand the user an interactive Claude Code to sign in with.

    A fresh install has a Claude Code inside it and no way to reach it: the
    bundled binary is under ``site-packages``, not on PATH, so "run `claude`" is
    an instruction that fails on the machine that most needs it. This runs the
    binary Inshirah itself would run, attached to the real terminal, and gets
    out of the way.
    """
    binary = claude_binary()
    if binary is None:
        print(MISSING)
        return 1
    print(f"Signing in to Claude Code:\n  {binary}\n")
    # `auth login` rather than the bare REPL: it does this one job and exits,
    # so the user is not left inside a second application wondering how to get
    # out of it, and it works on a machine with no browser — the flow prints a
    # URL and waits for the code, instead of trying to open something.
    return subprocess.call([binary, "auth", "login"])


def check(harness: Harness) -> int:
    """``--check`` — does this project load the way it would under `claude`?

    Doubles as the first-run diagnostic: the same probe that reports skills and
    MCP servers is the one that fails when Claude Code is missing or signed out,
    so that failure is answered with the fix rather than with its own wording.
    """
    try:
        environment = asyncio.run(probe(harness))
    except Exception as exc:
        fix = explain_setup_failure(exc)
        print(fix or f"could not start a session in {harness.project}: {exc}")
        return 1
    print(environment.report())
    return 1 if environment.broken_mcp else 0


def stats() -> int:
    """``--stats`` — show the counts, and offer to hand them over.

    The asking is done here rather than in ``core`` because it is a
    conversation with a person at a terminal, and ``core`` does not have one.
    What it must not do is proceed on silence: the prompt defaults to no, a
    pipe or a cron job is told it was not asked rather than being treated as
    consent, and ctrl-c at the prompt is an answer, not a crash.
    """
    print(usage.report())
    print()
    if not share.configured():
        print(share.UNCONFIGURED)
        return 0
    print(share.CONSENT)
    print()
    if not sys.stdin.isatty():
        print(share.NOT_INTERACTIVE)
        return 0
    try:
        answer = input("  Send them? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print(share.DECLINED)
        return 0
    print()
    if answer not in ("y", "yes"):
        print(share.DECLINED)
        return 0
    payload = usage.summary()
    if share.open_form(payload):
        print(share.SENT)
    else:
        print(share.NO_BROWSER.format(url=share.url(payload)))
    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    harness = harness_from(args)
    if args.login:
        raise SystemExit(login())
    if args.privacy:
        print(privacy_report(CONVERSATIONS))
        raise SystemExit(0)
    if args.stats:
        raise SystemExit(stats())
    if args.check:
        raise SystemExit(check(harness))
    if args.serve:
        raise SystemExit(serve(args, harness.project))
    # Below here a session is genuinely starting. The flags above all exit, and
    # counting them would make "sessions" mean "times the binary ran", which is
    # the denominator of every other number here.
    usage.start_session()
    InshirahApp(harness, storage_for(harness.project)).run()


if __name__ == "__main__":
    main()

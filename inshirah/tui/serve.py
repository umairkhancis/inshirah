"""Serve the TUI in a browser, on this machine.

``textual-serve`` runs the app locally and streams its terminal to a browser
over a websocket. So this is not the web client Phase 5 prepared for — there is
no HTML, no REST API, no responsive layout. It is the same TUI, drawn somewhere
else, and every feature comes along unchanged precisely because nothing is
reimplemented.

It is also not a hosted product. The server is on the user's own machine,
talking to their own Claude Code install, and the browser is a second front door
onto it for people who would rather not live in a terminal. Nothing about
``--serve`` involves a backend of ours, which is the whole reason it can be
offered at all: a hosted Inshirah would be a stranger's code and a stranger's
keys on someone else's infrastructure.

Each browser session spawns its own process, and therefore its own conversation.
Nothing is shared between tabs and nothing survives a refresh: the transcript
lives in memory in that process, and the registry that would let a session be
addressed by id and rehydrated is not wired up to this path.

The security shape is the part worth pausing on. The served app is Claude Code
with its tools, plus ``!command`` — so whoever reaches the port can read, write
and execute on *this* machine, and there is no authentication of any kind. On
loopback that is the same trust boundary as running the TUI yourself. On any
other interface it is a remote shell handed to the network, so that case is
refused rather than warned about: a warning assumes someone is reading the
output, and the person who most needs it is the one who typed ``--host 0.0.0.0``
into a script.
"""

import os
import shlex
import sys
import threading
import webbrowser
from argparse import Namespace

LOOPBACK = {"localhost", "127.0.0.1", "::1", "[::1]"}

# Saying it out loud is the point: the exposure has to be stated somewhere a
# reader of the command can see it, not buried in a default.
PUBLIC_GATE = "INSHIRAH_ALLOW_PUBLIC_HOST"

INSTALL_HINT = (
    "--serve needs textual-serve, which is not installed.\n"
    "    uv pip install 'inshirah[web]'   (or: uv pip install textual-serve)"
)

PUBLIC_REFUSAL = """\
╭─ REFUSED ─────────────────────────────────────────────────────────────────╮
│ Refusing to serve on {host}, which is not loopback.
│
│ Inshirah is Claude Code with its tools plus !command. Served anywhere but
│ loopback it becomes a remote shell on this machine, running as you, with
│ no login and no sandbox, for anyone who can reach the port.
│
│ On 127.0.0.1 it is the same trust boundary as running the TUI yourself.
│ If you genuinely mean to expose it, say so where it can be read:
│
│     {gate}=1 inshirah --serve --host {host}
╰───────────────────────────────────────────────────────────────────────────╯"""

EXPOSURE_WARNING = """\
╭─ WARNING ─────────────────────────────────────────────────────────────────╮
│ Serving on {host}, which is not loopback.
│
│ This app is Claude Code with its tools plus !command, so anyone who can
│ reach this port can read, write and run commands on this machine as you.
│ There is no login, no token and no sandbox.
│
│ Use --host 127.0.0.1 unless you genuinely intend that.
╰───────────────────────────────────────────────────────────────────────────╯"""


def tui_command(args: Namespace, project: str) -> str:
    """The TUI invocation each browser session runs.

    The project is passed explicitly rather than inherited: a served session
    starts wherever the server happens to be, and which directory it runs in is
    the whole of which CLAUDE.md, skills, agents and MCP servers it loads.
    """
    argv = [sys.executable, "-m", "inshirah.tui", "--cwd", project]
    argv += ["--permission-mode", args.permission_mode]
    if args.allow:
        argv += ["--allow", *args.allow]
    if args.deny:
        argv += ["--deny", *args.deny]
    if args.add_dir:
        argv += ["--add-dir", *args.add_dir]
    return shlex.join(argv)


def open_when_ready(url: str, opener=webbrowser.open, delay: float = 1.0) -> None:
    """Open the browser shortly after the server starts listening.

    ``Server.serve()`` blocks, so there is no "started" callback to hang this
    on, and opening before the socket is up gets a connection-refused page that
    the user then has to reload. A short timer is the honest version of waiting
    for a signal that is not offered.
    """
    threading.Timer(delay, opener, args=(url,)).start()


def serve(args: Namespace, project: str) -> int:
    if args.host not in LOOPBACK and not os.environ.get(PUBLIC_GATE):
        print(PUBLIC_REFUSAL.format(host=args.host, gate=PUBLIC_GATE))
        return 2

    if args.host not in LOOPBACK:
        print(EXPOSURE_WARNING.format(host=args.host))

    try:
        from textual_serve.server import Server
    except ImportError:
        print(INSTALL_HINT)
        return 1

    url = f"http://{args.host}:{args.port}"
    print(f"Inshirah in {project}")
    print(f"  {url}")
    if args.open_browser and args.host in LOOPBACK:
        open_when_ready(url)
    Server(
        tui_command(args, project),
        host=args.host,
        port=args.port,
        title="Inshirah",
    ).serve()
    return 0

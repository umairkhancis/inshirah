# Inshirah

**A thoughtful surface over Claude Code — one that keeps you in the middle of the work instead of routing around you.**

Inshirah is a terminal app (and, on the same machine, a browser one) that runs
Claude Code underneath, unchanged. Same agent, same tools, same `CLAUDE.md`,
same skills, agents, hooks and MCP servers. What changes is the surface:

- **Edit any message in place.** Not just the last one — any of them, yours or
  the model's. The edited version is the only one the model ever sees again.
  This is context management with your hands on it, rather than a context
  window that accumulates whatever happened to be said.
- **Branch a thread off any message.** Go down a rabbit hole from message 3
  without dragging the main conversation through it, Slack-style. The thread
  inherits the context; the conversation never sees the detour.
- **`!command`** runs a shell command and *holds* the output, so you can edit it
  before the model reads it — or drop it.
- **Slash commands** — the project's own, as Claude Code reports them.

The premise: AI is leverage on your judgment, not a substitute for it. A surface
that hands you a thousand lines you did not ask for and cannot account for is
not doing you a favour. `inshirah` is the other kind.

---

## Install

One command, on any machine:

```sh
# macOS and Linux
curl -LsSf https://raw.githubusercontent.com/umairkhancis/inshirah/main/scripts/install.sh | sh

# Windows
powershell -c "irm https://raw.githubusercontent.com/umairkhancis/inshirah/main/scripts/install.ps1 | iex"

# macOS, if you would rather use Homebrew
brew install umairkhancis/tap/inshirah
```

That is the whole prerequisite list. You do not need Python, `uv`, `pipx`, Node
or npm first — the installer fetches what it needs, into your home directory,
without sudo. Claude Code comes along with it, which is why the download is a
few hundred megabytes rather than a few hundred kilobytes.

If piping a script into a shell makes you uneasy — reasonable, and this is a
tool for people who think that way — [read it first](scripts/install.sh); it is sixty
lines. Or skip it entirely and do the two things it does:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh    # if you do not have uv
uv tool install inshirah
```

What the installer does *not* ship is a login. If you already use Claude Code,
it picks up the session you are signed in to and you are done. If you have never
signed in on this machine:

```sh
inshirah --login          # once — sign in, then /exit to come back
```

That runs the Claude Code that came with Inshirah, so there is nothing else to
install. The sign-in is Anthropic's, in your browser. Inshirah has no account
and no API key of its own, and never sees yours.

## Use it

```sh
cd ~/code/the-project
inshirah                        # in your terminal
inshirah --serve                # …or in your browser, on localhost
```

The directory you start in is the project: its `CLAUDE.md`, `.claude/settings.json`,
`.claude/skills`, `.claude/agents`, `.mcp.json` and plugins all load exactly as
they would under `claude`, because none of it is reimplemented here.

`--serve` runs the same app on your own machine and streams it to
`http://127.0.0.1:8000`. It is a second front door onto a local install, not a
hosted service — there is no server of ours in the picture, and serving it
anywhere but loopback is refused, because the app is Claude Code with shell
access and no login.

| | |
|---|---|
| `ctrl+e` | edit the selected message |
| `ctrl+t` | branch a thread off it |
| `ctrl+n` | new conversation |
| `ctrl+x` | export the conversation to markdown |
| `ctrl+i` | what this project loaded |
| `ctrl+g` | show/hide the conversation rail |

```sh
inshirah --check        # what this directory loads: skills, agents, MCP, memory
inshirah --privacy      # what leaves this machine, and where your data is
inshirah --stats        # what this copy has counted, and an offer to share it
inshirah --help         # flags that narrow what the agent may do
```

Every flag only ever *narrows* the harness — `--permission-mode`, `--allow`,
`--deny`, `--add-dir`. There is no flag that reconfigures Claude Code, because
your project already does that.

## What leaves your machine

Nothing, on its own. There is no Inshirah account and no Inshirah server, and
this program has no way to send anything anywhere — the package imports no HTTP
client at all, and `tests/test_privacy.py` fails the build if one is ever added.

- **Model traffic** goes to Anthropic through *your* Claude Code install, signed
  in as you, billed to you. Inshirah never sees a key of yours.
- **Conversations** are plain JSON under `~/.inshirah/projects/`, on your disk.
  Delete the directory and they are gone.
- **Your code** is read and written by Claude Code's own tools, in the directory
  you launched in, under the permission mode you chose.

Run `inshirah --privacy` to have the installed copy tell you the same thing with
your machine's real paths.

### The one number this project would like

`~/.inshirah/usage.json` is a file of integers, written as you work: how many
sessions, how many messages you edited, how many threads you branched. Never
prompts, never replies, never file names, never paths, never anything that
identifies you or this machine. `INSHIRAH_NO_USAGE=1` keeps none of it, and `rm`
forgets it.

`inshirah --stats` prints that file. If you would like to hand the numbers over,
it opens a form in your browser with them already filled in — you read them
there and press Submit, or you close the tab. Nothing is sent by the program,
which is why this is the only mechanism on offer: a project that promises it
cannot phone home does not then get to phone home about how well the promise is
going.

It is worth saying plainly why you are being asked. Inshirah has no analytics,
so the only evidence that editing a reply in place is useful to anyone other
than its author is the people who choose to say so. [Where the numbers go, and
what may ever be in them](docs/stats-form.md).

## Develop

```sh
uv venv && uv pip install -e '.[dev]'
pytest
```

The package is split so a client is a thin shell over a headless engine:
`inshirah.core` holds conversation state, the transcript and the harness, and
imports nothing from any front end; `inshirah.tui` is one client. A web client
would be a sibling of the TUI, not a rewrite.

## Licence

MIT. See [LICENSE](LICENSE).

---

*Inshirah (اِنْشِراح) — the opening, or expansion, of the chest.*

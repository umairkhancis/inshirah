"""The pieces the screen is built from.

Kept apart from ``app.py`` so that file is about behaviour — what a key does,
what a turn does — and this one is about appearance and local interaction.
Neither knows anything about Claude Code; they are handed ``Turn`` objects and
``Conversation`` objects by the core and draw what they are given.

The unit of reuse is :class:`ConversationPane`: a header, a scroll of messages
and a composer. The main column is one, the thread column is another. They
behave identically because they are the same widget, which is what makes a
thread feel like a conversation rather than a panel.
"""

from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message as TextualMessage
from textual.widgets import Button, Collapsible, Input, Markdown, Static

from inshirah.core import Conversation, SlashCommand, Turn
from inshirah.tui.design import GLYPHS

AUTHORS = {"user": "you", "assistant": "claude", "command": "command"}


def initials(role: str, shell: bool) -> str:
    if shell:
        return "$_"
    return {"user": "YO", "assistant": "CL", "command": "/_"}.get(role, "??")


class Avatar(Static):
    """A square of colour and two letters — who is talking, seen at a glance."""

    def __init__(self, role: str, shell: bool) -> None:
        super().__init__(initials(role, shell), classes=f"avatar {role}")
        if shell:
            self.add_class("shell")


class MessageRow(Horizontal):
    """One turn, drawn the way a chat app draws one.

    A turn under the full harness is often mostly tool calls, and an assistant
    entry can carry a tool call and no text at all — so the tools are drawn too,
    folded away, or the agent looks idle while it is rewriting your files.
    """

    class Selected(TextualMessage):
        def __init__(self, row: "MessageRow") -> None:
            super().__init__()
            self.row = row

    class ThreadRequested(TextualMessage):
        def __init__(self, row: "MessageRow") -> None:
            super().__init__()
            self.row = row

    def __init__(self, turn: Turn, replies: int = 0, branch: bool = False) -> None:
        self.turn = turn
        self.uuid = turn.uuid
        self.role = turn.role
        self.replies = replies
        # The message a thread hangs off, shown at the top of the thread column
        # for orientation. It belongs to the parent conversation, so it is not
        # something the thread's own keys may act on.
        self.branch = branch
        self.held = turn.uuid.startswith("pending:")
        self.shell = turn.role == "user" and turn.text.startswith("$ ")
        self.author = "shell" if self.shell else AUTHORS[turn.role]
        self.body_text = turn.text

        classes = ["message", turn.role]
        if self.shell:
            classes.append("shell")
        if self.held:
            classes.append("held")
        if branch:
            classes.append("branch")
        super().__init__(classes=" ".join(classes))

    def compose(self) -> ComposeResult:
        yield Avatar(self.role, self.shell)
        with Vertical(classes="message-main"):
            with Horizontal(classes="message-head"):
                yield Static(self.author, classes="author")
                if meta := self._meta():
                    yield Static(meta, classes="meta")
            if self.body_text:
                yield self._body()
            elif not self.turn.tools:
                yield Static(Text("…", style="dim"), classes="body")
            if self.turn.tools:
                calls = [
                    Static(f"{GLYPHS['tool']} {tool}", classes="tool-call")
                    for tool in self.turn.tools
                ]
                plural = "" if len(calls) == 1 else "s"
                yield Collapsible(*calls, title=f"{len(calls)} tool call{plural}", collapsed=True)
            if self.replies:
                plural = "y" if self.replies == 1 else "ies"
                yield Static(
                    f"{GLYPHS['thread']} {self.replies} repl{plural}", classes="replies"
                )

    def _meta(self) -> str:
        if self.held:
            return "held · goes with your next message"
        return ""

    def _body(self):
        """Prose gets markdown; anything literal keeps its own spacing.

        Command output and questions are quoted material — reflowing them or
        eating their backticks would misreport what was said or run.
        """
        if self.role == "assistant" and not self.shell:
            return Markdown(self.body_text, classes="body")
        # Everything else is quoted material shown verbatim: a question, command
        # output, a shell transcript. Markdown would reflow it and swallow the
        # angle brackets in a usage line like "/model <name>".
        return Static(Text(self.body_text, no_wrap=False), classes="body")

    def on_click(self, event) -> None:
        if not self.uuid or self.branch:
            return
        self.post_message(self.Selected(self))
        # The reply count is the affordance a chat app trains you to click.
        if isinstance(event.widget, Static) and event.widget.has_class("replies"):
            self.post_message(self.ThreadRequested(self))


class Working(Static):
    """The gap between sending and hearing back, drawn rather than left blank."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        super().__init__(classes="working")
        self.uuid = ""  # never selectable: there is nothing here to edit
        self._frame = 0

    def on_mount(self) -> None:
        self._tick()
        self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % len(self.FRAMES)
        self.update(f"{self.FRAMES[self._frame]}  claude is working")


class Starter(Static):
    """A suggestion on the landing screen that fills the composer when clicked."""

    class Chosen(TextualMessage):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self, glyph: str, headline: str, prompt: str) -> None:
        super().__init__(classes="starter")
        self.prompt = prompt
        self._glyph = glyph
        self._headline = headline

    def compose(self) -> ComposeResult:
        yield Static(self._glyph, classes="starter-glyph")
        with Vertical(classes="starter-main"):
            yield Static(self._headline, classes="starter-headline")
            yield Static(self.prompt, classes="starter-prompt")

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.prompt))


class Welcome(Vertical):
    """The landing screen: what this is, where you are, and what to do next.

    An empty transcript with a blinking cursor tells a newcomer nothing. This
    says what is running underneath, which project it opened, and offers four
    things to click — the fastest way to learn what the surface is for is to
    watch it do something.
    """

    STARTERS = (
        ("✦", "Get oriented", "Walk me through what this project does and how it is laid out."),
        ("⚙", "Put it to work", "Find the riskiest untested code path and write a test for it."),
        ("$", "Bring the terminal", "!git log --oneline -10"),
        ("⤷", "Try a thread", "Explain database indexes, briefly."),
    )

    def __init__(self, project: str, environment_line: str) -> None:
        super().__init__(id="welcome")
        self.project = project
        self.environment_line = environment_line

    def compose(self) -> ComposeResult:
        with Vertical(classes="welcome-card"):
            yield Static("inshirah", classes="wordmark")
            yield Static(
                "A conversation you can rewrite. Claude Code runs underneath — "
                "the same agent, the same tools, this project's own CLAUDE.md, "
                "skills, agents and MCP servers.",
                classes="tagline",
            )
            with Horizontal(classes="facts"):
                yield Static(f"{GLYPHS['hash']} {self.project}", classes="fact")
                yield Static(self.environment_line, classes="fact")
            yield Static("START WITH", classes="section")
            for glyph, headline, prompt in self.STARTERS:
                yield Starter(glyph, headline, prompt)
            yield Static(
                "Every message can be rewritten in place with ctrl+e — the model "
                "only ever sees the new version. Any message can start a thread "
                "with ctrl+t, which branches the conversation without disturbing "
                "this one.",
                classes="footnote",
            )


class CommandOption(Static):
    """One row in the slash-command menu."""

    def __init__(self, command: SlashCommand, index: int) -> None:
        super().__init__(classes="command-option")
        self.command = command
        self.index = index

    def compose(self) -> ComposeResult:
        # Text(), not a plain string: a hint and a description come from the CLI
        # and are shown verbatim, so neither gets a chance to be read as markup.
        yield Static(f"/{self.command.name}", classes="command-name")
        yield Static(Text(self.command.argument_hint), classes="command-args")
        yield Static(Text(self.command.summary), classes="command-desc")
        if self.command.source:
            yield Static(self.command.source, classes="command-source")

    def on_click(self) -> None:
        self.post_message(CommandMenu.Picked(self.command))


class CommandMenu(VerticalScroll):
    """What you can type after ``/``, offered while you type it.

    The list is the CLI's, not ours — Inshirah never decides what a project
    offers, it only shows what Claude Code said it has.
    """

    class Picked(TextualMessage):
        def __init__(self, command: SlashCommand) -> None:
            super().__init__()
            self.command = command

    def __init__(self) -> None:
        super().__init__(classes="command-menu")
        self.display = False
        self.matches: list[SlashCommand] = []
        self.index = 0

    @property
    def visible_menu(self) -> bool:
        return self.display and bool(self.matches)

    async def offer(self, commands: list[SlashCommand]) -> None:
        keep = self.current.name if self.matches and self.index < len(self.matches) else None
        self.matches = commands
        if not commands:
            self.close()
            return
        self.index = next(
            (i for i, c in enumerate(commands) if c.name == keep), 0
        )
        await self.remove_children()
        await self.mount_all(CommandOption(c, i) for i, c in enumerate(commands))
        self.display = True
        self._paint()

    def close(self) -> None:
        self.display = False
        self.matches = []
        self.index = 0

    @property
    def current(self) -> SlashCommand | None:
        if not self.matches:
            return None
        return self.matches[max(0, min(self.index, len(self.matches) - 1))]

    def move(self, delta: int) -> None:
        if not self.matches:
            return
        self.index = (self.index + delta) % len(self.matches)
        self._paint()

    def _paint(self) -> None:
        for option in self.query(CommandOption):
            option.set_class(option.index == self.index, "current")
            if option.index == self.index:
                option.scroll_visible()


class ComposerInput(Input):
    """The prompt box, which hands its keys to the command menu when one is open.

    Input acts on enter and tab itself, so the menu has to be offered them
    first — otherwise picking a command would send it instead of completing it.
    """

    MENU_KEYS = ("up", "down", "tab", "enter", "escape")

    async def _on_key(self, event: events.Key) -> None:
        composer = self.composer
        if (
            composer is not None
            and composer.menu.visible_menu
            and event.key in self.MENU_KEYS
        ):
            event.stop()
            event.prevent_default()
            composer.menu_key(event.key)
            return
        await super()._on_key(event)

    @property
    def composer(self) -> "Composer | None":
        for node in self.ancestors:
            if isinstance(node, Composer):
                return node
        return None


class Composer(Vertical):
    """The input, plus a line that says what enter is about to do."""

    class Submitted(TextualMessage):
        def __init__(self, composer: "Composer", text: str) -> None:
            super().__init__()
            self.composer = composer
            self.text = text

    def __init__(self, placeholder: str) -> None:
        super().__init__(classes="composer")
        self._placeholder = placeholder
        self.commands: tuple[SlashCommand, ...] = ()
        # What a completion just put in the box. Without this the menu reopens
        # on its own result — "/context" still looks like a half-typed name —
        # and every command took an extra keypress to get past its own menu.
        self._completed: str | None = None

    def compose(self) -> ComposeResult:
        yield CommandMenu()
        with Horizontal(classes="composer-row"):
            yield Static(GLYPHS["user"], classes="composer-glyph")
            yield ComposerInput(placeholder=self._placeholder, classes="composer-input")
        yield Static("", classes="composer-hint")

    @property
    def input(self) -> Input:
        return self.query_one(ComposerInput)

    @property
    def menu(self) -> CommandMenu:
        return self.query_one(CommandMenu)

    def know_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self.commands = commands

    async def refresh_menu(self) -> None:
        """Offer commands while the name is still being typed, and not after.

        Once there is a space the rest is arguments, which belong to the command
        and are none of this menu's business.
        """
        value = self.input.value
        if value == self._completed:
            self._completed = None  # only the completion itself is suppressed
            self.menu.close()
            return
        self._completed = None
        if not value.startswith("/") or " " in value or self.input.disabled:
            self.menu.close()
            return
        await self.menu.offer([c for c in self.commands if c.matches(value)])

    def menu_key(self, key: str) -> None:
        if key == "escape":
            self.menu.close()
        elif key == "up":
            self.menu.move(-1)
        elif key == "down":
            self.menu.move(1)
        elif key == "tab":
            if (command := self.menu.current) is not None:
                self.accept(command)
        elif key == "enter":
            # Enter means "do it". A command needing no arguments has nothing
            # left to type, so asking for a second enter is pure ceremony.
            if (command := self.menu.current) is not None:
                self.accept(command, run=True)

    def accept(self, command: SlashCommand, run: bool = False) -> None:
        """Complete the name; a command that takes arguments waits for them.

        ``run`` sends it straight away when there is nothing left to type, so
        picking such a command off the menu is a single keypress.
        """
        self.menu.close()
        text = f"/{command.name}" + (" " if command.takes_arguments else "")
        if run and not command.takes_arguments:
            self.input.value = ""
            self._completed = None
            self.post_message(self.Submitted(self, text))
            return
        self._completed = text
        self.input.value = text
        self.input.cursor_position = len(text)
        self.input.focus()
        self.refresh_hint()

    def focus_input(self) -> None:
        self.input.focus()

    def set_busy(self, busy: bool) -> None:
        self.input.disabled = busy
        self.refresh_hint()

    def refresh_hint(self, note: str | None = None) -> None:
        """Shell mode is a different thing entirely; the composer has to show it."""
        shell = self.input.value.startswith("!")
        self.set_class(shell, "shell")
        self.query_one(".composer-glyph", Static).update(
            GLYPHS["shell"] if shell else GLYPHS["user"]
        )
        if note is None:
            if self.input.disabled:
                note = "working…"
            elif shell:
                note = "runs here · output is held for your next message"
            elif self.input.value.startswith("/"):
                note = "↑↓ to choose · tab to complete · enter to run"
            else:
                note = "enter to send · / for commands · ! to run a shell command"
        self.query_one(".composer-hint", Static).update(note)

    @on(Input.Changed)
    async def typed(self) -> None:
        self.refresh_hint()
        await self.refresh_menu()

    @on(CommandMenu.Picked)
    def command_picked(self, event: "CommandMenu.Picked") -> None:
        event.stop()
        self.accept(event.command)

    @on(Input.Submitted)
    def submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.menu.close()
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self.post_message(self.Submitted(self, text))


class ConversationPane(Vertical):
    """A header, a scroll of messages and a composer, over one conversation.

    Both columns are one of these. A thread behaving exactly like the main
    conversation — same editing, same ``!``, same threading — is the whole
    reason it is the same widget rather than a read-only side panel.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(id=f"{kind}-pane", classes="pane")
        self.kind = kind  # "main" | "thread"
        self.conversation: Conversation | None = None
        self.selected: MessageRow | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="pane-head"):
            yield Static("", classes="pane-title")
            yield Static("", classes="pane-meta")
            if self.kind == "thread":
                yield Button(GLYPHS["close"], classes="pane-close", id="close-thread")
        yield VerticalScroll(classes="messages")
        yield Composer(
            "Reply in thread…" if self.kind == "thread" else "Message…"
        )

    @property
    def composer(self) -> Composer:
        return self.query_one(Composer)

    @property
    def rows(self) -> list[MessageRow]:
        return list(self.query(MessageRow))

    async def show(self, conversation: Conversation | None, welcome: Welcome | None = None) -> None:
        self.conversation = conversation
        await self.draw(welcome=welcome)

    async def draw(self, pending: bool = False, welcome: Welcome | None = None) -> None:
        """Redraw from the conversation — the store is the source of truth."""
        scroll = self.query_one(".messages", VerticalScroll)
        await scroll.remove_children()
        self.selected = None
        if self.conversation is None:
            self._head("", "")
            return

        widgets: list = []
        # A thread opens on the message it hangs off, so the reply has something
        # to be a reply *to* — the same orientation Slack gives you.
        if self.kind == "thread" and (parent := self.conversation.branch_turn):
            widgets.append(MessageRow(parent, branch=True))
            widgets.append(Static(self._divider(), classes="thread-divider"))
        # ``own_turns``, not ``turns``: a started thread's transcript begins with
        # everything up to the branch point, which the model needs and the reader
        # has already read.
        widgets.extend(
            MessageRow(turn, self.conversation.reply_count(turn.uuid))
            for turn in self.conversation.own_turns
        )
        widgets.extend(MessageRow(turn) for turn in self.conversation.pending_turns)
        if pending:
            widgets.append(Working())
        if not widgets and welcome is not None:
            widgets.append(welcome)
        await scroll.mount_all(widgets)
        self._refresh_head()
        scroll.scroll_end(animate=False)

    def _divider(self) -> str:
        count = len(self.conversation.own_turns)
        if not count:
            return "── no replies yet ──"
        plural = "y" if count == 1 else "ies"
        return f"── {count} repl{plural} ──"

    def _refresh_head(self) -> None:
        conversation = self.conversation
        if self.kind == "thread":
            self._head(f"{GLYPHS['thread']} {conversation.title(40)}", "thread")
        else:
            messages = len(conversation.turns)
            threads = len(conversation.walk()) - 1
            meta = f"{messages} message{'' if messages == 1 else 's'}"
            if threads:
                meta += f" · {threads} thread{'' if threads == 1 else 's'}"
            self._head(f"{GLYPHS['hash']} {conversation.display_name(40)}", meta)

    def _head(self, title: str, meta: str) -> None:
        self.query_one(".pane-title", Static).update(title)
        self.query_one(".pane-meta", Static).update(meta)

    def select(self, row: MessageRow) -> None:
        for other in self.rows:
            other.remove_class("selected")
        row.add_class("selected")
        self.selected = row
        row.scroll_visible()

    def move_selection(self, delta: int) -> None:
        rows = [r for r in self.rows if r.uuid and not r.branch]
        if not rows:
            return
        if self.selected in rows:
            index = rows.index(self.selected) + delta
        else:
            index = len(rows) - 1
        self.select(rows[max(0, min(index, len(rows) - 1))])

    def target(self) -> MessageRow | None:
        """What an editing or threading key should act on.

        Never the branch-point message: it is the parent's, and threading off it
        again would hang a thread on a message this conversation does not have.
        """
        if self.selected is not None and self.selected.uuid and not self.selected.branch:
            return self.selected
        rows = [r for r in self.rows if r.uuid and not r.branch]
        return rows[-1] if rows else None


class RailItem(Static):
    """One conversation in the rail."""

    class Chosen(TextualMessage):
        def __init__(self, tree_id: str) -> None:
            super().__init__()
            self.tree_id = tree_id

    class DeleteRequested(TextualMessage):
        def __init__(self, tree_id: str) -> None:
            super().__init__()
            self.tree_id = tree_id

    def __init__(self, summary: dict, current: bool) -> None:
        super().__init__(classes="rail-item")
        self.tree_id = summary["id"]
        self.summary = summary
        if current:
            self.add_class("current")

    def compose(self) -> ComposeResult:
        marker = GLYPHS["dot"] if self.has_class("current") else " "
        # Text(): the name is whatever was first asked here, or whatever the
        # user typed into rename, and neither is markup.
        yield Static(Text(f"{marker} {self.summary['name']}"), classes="rail-name")
        bits = []
        if self.summary["messages"]:
            bits.append(str(self.summary["messages"]))
        if self.summary["threads"]:
            bits.append(f"{GLYPHS['thread']}{self.summary['threads']}")
        yield Static(" ".join(bits), classes="rail-count")
        yield Static(GLYPHS["close"], classes="rail-delete")

    def on_click(self, event) -> None:
        # One row, two targets — the ✕ throws the conversation away, everything
        # else opens it. Drawn always rather than on hover: a row you can only
        # discover by finding it with the mouse is not an affordance, and the
        # confirm is what stands between a mis-click and a loss.
        if isinstance(event.widget, Static) and event.widget.has_class("rail-delete"):
            event.stop()
            self.post_message(self.DeleteRequested(self.tree_id))
            return
        self.post_message(self.Chosen(self.tree_id))


class ConversationRail(Vertical):
    """The list of conversations, and the way to start another."""

    class NewRequested(TextualMessage):
        pass

    def compose(self) -> ComposeResult:
        yield Static("inshirah", id="wordmark-small")
        yield Button(f"{GLYPHS['new']}  New conversation", id="new-conversation")
        yield Static("CONVERSATIONS", classes="rail-section")
        yield VerticalScroll(id="rail-items")

    async def sync(self, summaries: list[dict], current_id: str | None) -> None:
        items = self.query_one("#rail-items", VerticalScroll)
        await items.remove_children()
        await items.mount_all(
            RailItem(summary, summary["id"] == current_id) for summary in summaries
        )

    @on(Button.Pressed, "#new-conversation")
    def new_conversation(self, event: Button.Pressed) -> None:
        event.stop()
        self.post_message(self.NewRequested())

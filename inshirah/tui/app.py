"""Inshirah — a TUI over Claude Code whose messages can be edited in place.

Claude Code runs underneath, unchanged: its agent preset, its tools, its
settings and the CLAUDE.md of the directory you launched in. Inshirah supplies
the surface — editing any message in place, and branching a thread off any
message — not a second agent.

Any message can be edited, not just the last reply. Editing discards every
message after it: a fact usually appears in later messages too, and a stale copy
left behind contradicts the edit — the model then sides with the stale copy (or,
with Claude, the self-contradicting history can be refused outright).

The screen is three columns, the way a chat app is: the conversations you have
open, the one you are in, and the thread you branched off it. The thread is a
column rather than a drill-down because the point of a thread is to go deep on
one message *without losing* the conversation it came from — replacing the
transcript with it would defeat that.
"""

import os

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Static, TextArea

from inshirah.core import (
    Conversation,
    ConversationBusy,
    ConversationRegistry,
    Harness,
    MemoryStorage,
    SlashCommand,
    Storage,
    Turn,
    explain_setup_failure,
    load_commands,
    split_command,
)
from inshirah.tui import design, permissions
from inshirah.tui.delete import DeleteConversation
from inshirah.tui.design import GLYPHS
from inshirah.tui.environment_report import EnvironmentReport
from inshirah.tui.rename import RenameConversation
from inshirah.tui.widgets import (
    CommandMenu,
    Composer,
    ConversationPane,
    ConversationRail,
    MessageRow,
    RailItem,
    Starter,
    Welcome,
)


class InshirahApp(App):
    CSS_PATH = "inshirah.tcss"

    # priority so a focused Input or TextArea cannot swallow these first
    BINDINGS = [
        Binding("ctrl+e", "edit", "Edit message", priority=True),
        Binding("ctrl+t", "open_thread", "Thread", priority=True),
        Binding("ctrl+n", "new_conversation", "New", priority=True),
        Binding("ctrl+x", "export", "Export", priority=True),
        Binding("ctrl+i", "show_environment", "What loaded", priority=True),
        Binding("ctrl+g", "toggle_rail", "Rail", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        # Reachable by key and through the command palette; the footer stays
        # short enough to read.
        Binding("ctrl+s", "save_edit", "Save edit", priority=True, show=False),
        Binding("ctrl+r", "rename", "Rename", priority=True, show=False),
        Binding("ctrl+d", "delete_conversation", "Delete", priority=True, show=False),
        Binding("ctrl+up", "select_prev", "Select earlier", priority=True, show=False),
        Binding("ctrl+down", "select_next", "Select later", priority=True, show=False),
        Binding("escape", "cancel_edit", "Cancel", priority=True, show=False),
    ]

    def __init__(
        self, harness: Harness | None = None, storage: Storage | None = None
    ) -> None:
        super().__init__()
        self.harness = harness or Harness()
        # The permission prompt must exist before the first turn: with no
        # can_use_tool callback the SDK raises mid-turn the moment Claude Code
        # wants to ask about a command. The registry hands it to every
        # conversation it creates or reopens.
        self.registry = ConversationRegistry(
            storage or MemoryStorage(),
            harness=self.harness,
            can_use_tool=permissions.handler(self),
        )
        self.conversation: Conversation | None = None  # the tree in the main pane
        self.thread: Conversation | None = None  # the thread in the right pane
        self.editor: TextArea | None = None
        self.editing: MessageRow | None = None
        self.active = "main"  # which pane the editing keys act on
        # What this project offers. Held here rather than on a conversation:
        # starting a new one must not empty the menu, because the commands are
        # the directory's, not the conversation's.
        self.commands: tuple[SlashCommand, ...] = ()
        self._announced = False  # what loaded is reported once, not every turn

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """Values for the tokens the stylesheet uses that are ours, not Textual's.

        The CSS is parsed before any theme is applied, so ``$rail`` and friends
        have to exist before ``design.register`` runs or the stylesheet will not
        parse at all.
        """
        return design.VARIABLE_DEFAULTS

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Let a modal have Escape back.

        The editing bindings are ``priority`` so a focused Input cannot swallow
        them — but priority also beats a screen's own bindings, so Escape was
        reaching a no-op instead of dismissing the permission prompt. Disabling
        the binding whenever a modal is on top, or there is nothing to cancel,
        lets it through.
        """
        if action == "cancel_edit":
            if len(self.screen_stack) > 1:
                return False
            if self._command_menu_open():
                return False  # escape closes the menu, not the thread
            return self.editor is not None or self.thread is not None
        if action == "delete_conversation":
            # Priority beats a screen's own bindings, so without this ctrl+d
            # inside the confirm would stack a second one on top of it.
            return len(self.screen_stack) == 1
        return True

    def _command_menu_open(self) -> bool:
        return any(menu.visible_menu for menu in self.query(CommandMenu))

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("", id="where")
            yield Static("", id="mode")
            yield Static("", id="loaded")
        with Horizontal(id="body"):
            yield ConversationRail(id="rail")
            yield ConversationPane("main")
            yield ConversationPane("thread")
        yield Footer()

    async def on_mount(self) -> None:
        design.register(self)
        self.title = "inshirah"
        self.query_one("#thread-pane").add_class("hidden")
        # Reopen what was here last, or start the first conversation.
        existing = self.registry.listing()
        self.conversation = (
            self.registry.get(existing[0]["id"]) if existing else self.registry.create()
        )
        await self.refresh_all()
        self.main_pane.composer.focus_input()
        self.discover_commands()

    @work(exclusive=True)
    async def discover_commands(self) -> None:
        """Ask the CLI what commands this project has.

        Free — the list comes back with the initialize response, so no turn is
        spent — but it starts the CLI, hence a worker. Every turn refreshes it
        afterwards, so a command added to ``.claude/commands`` mid-session
        appears without a restart.
        """
        try:
            commands = await load_commands(self.harness)
        except Exception:
            return  # the menu is a convenience; typing the command still works
        self.commands = commands or self.commands
        self._share_commands()

    def _share_commands(self) -> None:
        """Keep the newest list, and give it to every conversation and composer.

        A turn refreshes the list on whichever conversation ran it, so that is
        the freshest source when it has one; a conversation that has never run a
        turn — a brand new one, or the one ``/clear`` just made — gets handed
        what the session already knows instead of starting empty.
        """
        if self.conversation is not None:
            if self.conversation.commands:
                self.commands = self.conversation.commands
            else:
                self.conversation.offer_commands(self.commands)
        for pane in (self.main_pane, self.thread_pane):
            pane.composer.know_commands(self.commands)

    # --- the two panes ----------------------------------------------------

    @property
    def main_pane(self) -> ConversationPane:
        return self.query_one("#main-pane", ConversationPane)

    @property
    def thread_pane(self) -> ConversationPane:
        return self.query_one("#thread-pane", ConversationPane)

    @property
    def pane(self) -> ConversationPane:
        """The pane the editing and threading keys act on."""
        if self.active == "thread" and self.thread is not None:
            return self.thread_pane
        return self.main_pane

    def pane_of(self, widget) -> ConversationPane:
        for node in widget.ancestors_with_self:
            if isinstance(node, ConversationPane):
                return node
        return self.main_pane

    # --- drawing ----------------------------------------------------------

    async def refresh_all(self) -> None:
        """Redraw everything from the core — it is the source of truth."""
        await self.main_pane.show(self.conversation, welcome=self._welcome())
        if self.thread is None:
            self.thread_pane.add_class("hidden")
            await self.thread_pane.show(None)
        else:
            self.thread_pane.remove_class("hidden")
            await self.thread_pane.show(self.thread)
        await self.refresh_rail()
        self._refresh_topbar()
        self._share_commands()
        for pane in (self.main_pane, self.thread_pane):
            pane.composer.refresh_hint()

    async def refresh_rail(self) -> None:
        current = self.conversation.id if self.conversation else None
        await self.query_one(ConversationRail).sync(self.registry.listing(), current)

    def _project(self) -> str:
        project = self.harness.project
        home = os.path.expanduser("~")
        return "~" + project[len(home) :] if project.startswith(home) else project

    def _refresh_topbar(self) -> None:
        self.query_one("#where", Static).update(f"{GLYPHS['hash']} {self._project()}")
        self.query_one("#mode", Static).update(self.harness.permission_mode)
        self.query_one("#loaded", Static).update(self._loaded_line())
        if self.conversation is not None:
            self.sub_title = self.conversation.display_name()

    def _loaded_line(self) -> str:
        """What Claude Code resolved here — kept in view, not behind a key.

        A skill that failed to parse or an MCP server that died looks exactly
        like one that works, so the counts are worth stating.
        """
        environment = self.conversation.environment if self.conversation else None
        if environment is None:
            return "ctrl+i after the first turn to see what loaded"
        if environment.broken_mcp:
            return f"! {', '.join(environment.broken_mcp)} did not start"
        return environment.summary()

    def _welcome(self) -> Welcome:
        return Welcome(self._project(), self._loaded_line())

    # --- conversations ----------------------------------------------------

    @on(ConversationRail.NewRequested)
    async def new_conversation(self) -> None:
        await self.action_new_conversation()

    @on(RailItem.Chosen)
    async def conversation_chosen(self, event: RailItem.Chosen) -> None:
        """Switching conversations closes the thread: it belonged to the old one."""
        if self.conversation is not None and event.tree_id == self.conversation.id:
            return
        self.conversation = self.registry.get(event.tree_id)
        self.thread = None
        self.active = "main"
        await self.refresh_all()
        self.main_pane.composer.focus_input()

    async def action_new_conversation(self) -> None:
        self.conversation = self.registry.create()
        self.thread = None
        self.active = "main"
        await self.refresh_all()
        self.main_pane.composer.focus_input()

    @on(RailItem.DeleteRequested)
    def rail_delete_requested(self, event: RailItem.DeleteRequested) -> None:
        """The ✕ acts on that row, which need not be the one you are in."""
        self.confirm_delete(event.tree_id)

    def action_delete_conversation(self) -> None:
        """ctrl+d acts on the conversation in front of you."""
        if self.conversation is not None:
            self.confirm_delete(self.conversation.id)

    @work
    async def confirm_delete(self, tree_id: str) -> None:
        # A worker because push_screen_wait needs one, as with rename.
        summary = next(
            (s for s in self.registry.listing() if s["id"] == tree_id), None
        )
        if summary is None:  # already gone; nothing to ask about
            return
        if not await self.push_screen_wait(DeleteConversation(summary)):
            return
        await self.delete_conversation(tree_id)

    async def delete_conversation(self, tree_id: str) -> None:
        """Drop it, and make sure something is still on screen afterwards.

        Deleting the conversation you are in leaves the main pane pointing at
        nothing, so the next one down the rail takes its place — and if it was
        the last one, a fresh conversation does, because an app with no
        conversation open has no composer to type in.
        """
        try:
            self.registry.delete(tree_id)
        except ConversationBusy:
            self.notify(
                "That conversation is mid-turn. Wait for the reply, then "
                "delete it.",
                severity="warning",
            )
            return
        if self.conversation is not None and self.conversation.id == tree_id:
            remaining = self.registry.listing()
            self.conversation = (
                self.registry.get(remaining[0]["id"])
                if remaining
                else self.registry.create()
            )
            self.thread = None  # it belonged to the conversation just deleted
            self.active = "main"
        await self.refresh_all()
        self.notify("Conversation deleted.")
        self.pane.composer.focus_input()

    @on(Composer.Submitted)
    async def composer_submitted(self, event: Composer.Submitted) -> None:
        pane = self.pane_of(event.composer)
        self.active = pane.kind
        if pane.conversation is None:
            return
        if event.text.startswith("!"):
            # Bash mode, as in Claude Code's own REPL: run it, hold the output
            # for the next prompt, and ask the model nothing.
            if command := event.text[1:].strip():
                self.run_command(pane, command)
            return
        if await self.run_local_command(event.text):
            return
        self.run_send(pane, event.text)

    async def run_local_command(self, text: str) -> bool:
        """The two commands that act on this surface rather than on the agent.

        Everything else is sent through untouched, so the CLI expands arguments,
        ``!`` blocks and ``@file`` references exactly as it would under
        ``claude`` — a second implementation here would only drift from that.

        ``/clear`` and ``/rename`` are different: the CLI's own versions act on
        a session and a conversation name that this app draws itself. Its
        ``/clear`` starts a fresh session and leaves the old one open, which is
        what a new conversation is here; sent through, it would swap the session
        underneath us with nothing on screen to show for it.
        """
        name, arguments = split_command(text)
        if name == "clear":
            self.conversation = self.registry.create(name=arguments or None)
            self.thread = None
            self.active = "main"
            await self.refresh_all()
            self.main_pane.composer.focus_input()
            self.notify("New conversation — the previous one is still in the rail.")
            return True
        if name == "rename":
            if arguments:
                self.registry.rename(self.conversation.id, arguments)
                await self.refresh_all()
            else:
                self.action_rename()
            return True
        return False

    @on(Starter.Chosen)
    def starter_chosen(self, event: Starter.Chosen) -> None:
        composer = self.main_pane.composer
        composer.input.value = event.text
        composer.focus_input()

    @work
    async def action_rename(self) -> None:
        # A worker because push_screen_wait needs one: a binding's action runs on
        # the message pump, where waiting on a screen would deadlock the app.
        if self.conversation is None:
            return
        name = await self.push_screen_wait(
            RenameConversation(self.conversation.display_name())
        )
        if name is None:
            return
        self.registry.rename(self.conversation.id, name)
        await self.refresh_all()

    # --- sending ----------------------------------------------------------

    def report_failure(self, prefix: str, exc: BaseException) -> None:
        """Say what went wrong, and for a first-run problem say what to do.

        A new user's first failure is usually that Claude Code is missing or
        signed out, and "Send failed: Claude Code not found" tells someone who
        installed a Python package nothing they can act on. The toast is held
        open because it is instructions to follow, not a status to glance at.
        """
        fix = explain_setup_failure(exc)
        if fix:
            self.notify(fix, title="Set up Claude Code", severity="error", timeout=30)
        else:
            self.notify(f"{prefix}: {exc}", severity="error")

    @work
    async def run_send(self, pane: ConversationPane, text: str) -> None:
        conversation = pane.conversation
        pane.composer.set_busy(True)
        conversation.turns.append(Turn("user", text, ""))  # echo it immediately
        await pane.draw(pending=True)
        failed = None
        try:
            await conversation.send(text)
        except Exception as exc:  # surface failures instead of hanging on "…"
            failed = exc
        finally:
            self.registry.save(conversation)
            await self.refresh_all()
            pane.composer.set_busy(False)
            if failed is not None:
                # The turn was rolled back out of the transcript; keep the text.
                pane.composer.input.value = text
                self.report_failure("Send failed", failed)
            self._announce_environment()
            pane.composer.focus_input()

    @work
    async def run_command(self, pane: ConversationPane, command: str) -> None:
        """``!cmd`` — a worker, so a slow command cannot freeze the UI."""
        pane.composer.set_busy(True)
        failed = None
        try:
            await pane.conversation.run_shell(command)
        except Exception as exc:
            failed = exc
        finally:
            await pane.draw()
            pane.composer.set_busy(False)
            if failed is not None:
                pane.composer.input.value = f"!{command}"
                self.notify(f"Command failed to run: {failed}", severity="error")
            else:
                self.notify(
                    "Output held — edit it with ctrl+e, then send a message to "
                    "pass it to the AI."
                )
            pane.composer.focus_input()

    def _announce_environment(self) -> None:
        """Say what this project loaded — once, after the first turn."""
        environment = self.conversation.environment if self.conversation else None
        if environment is None or self._announced:
            return
        self._announced = True
        self.notify(f"{environment.summary()} — ctrl+i for detail")
        if environment.broken_mcp:
            self.notify(
                f"MCP server(s) did not start: {', '.join(environment.broken_mcp)}",
                severity="error",
            )

    def action_show_environment(self) -> None:
        environment = self.conversation.environment if self.conversation else None
        if environment is None:
            self.notify(
                "Not known yet — send a message first. Claude Code does not "
                "report what it loaded until a turn starts.",
                severity="warning",
            )
            return
        self.push_screen(EnvironmentReport(environment))

    # --- selection --------------------------------------------------------

    @on(MessageRow.Selected)
    def row_selected(self, event: MessageRow.Selected) -> None:
        pane = self.pane_of(event.row)
        self.active = pane.kind
        pane.select(event.row)

    def action_select_prev(self) -> None:
        self.pane.move_selection(-1)

    def action_select_next(self) -> None:
        self.pane.move_selection(1)

    def action_toggle_rail(self) -> None:
        self.query_one("#rail").toggle_class("hidden")

    # --- threads ----------------------------------------------------------

    @on(MessageRow.ThreadRequested)
    async def thread_requested(self, event: MessageRow.ThreadRequested) -> None:
        await self.open_thread_on(self.pane_of(event.row), event.row)

    async def action_open_thread(self) -> None:
        pane = self.pane
        target = pane.target()
        if target is None or self.editor is not None:
            self.notify(
                "Nothing to branch from yet — say something here first."
                if pane.kind == "thread"
                else "Select a message to open its thread.",
                severity="warning",
            )
            return
        await self.open_thread_on(pane, target)

    async def open_thread_on(self, pane: ConversationPane, row: MessageRow) -> None:
        if pane.conversation is None or not row.uuid or row.uuid.startswith("pending:"):
            return
        if row.branch:  # the parent's message, shown here only for orientation
            return
        self.thread = pane.conversation.thread_for(row.uuid)
        self.active = "thread"
        await self.refresh_all()
        self.thread_pane.composer.focus_input()

    @on(Button.Pressed, "#close-thread")
    async def close_thread_button(self, event: Button.Pressed) -> None:
        event.stop()
        await self.close_thread()

    async def close_thread(self) -> None:
        """Out of the thread, back to whatever it hangs off.

        A nested thread steps up one level rather than closing outright, so
        going deep is reversible one step at a time.
        """
        if self.thread is None:
            return
        parent = self.thread.parent
        self.thread = parent if parent is not None and parent.parent is not None else None
        self.active = "main" if self.thread is None else "thread"
        await self.refresh_all()
        self.pane.composer.focus_input()

    # --- editing ----------------------------------------------------------

    def action_edit(self) -> None:
        pane = self.pane
        target = pane.target()
        if target is None or self.editor is not None or pane.conversation is None:
            self.notify("Nothing to edit yet.", severity="warning")
            return
        turn = next(
            (
                t
                for t in [*pane.conversation.turns, *pane.conversation.pending_turns]
                if t.uuid == target.uuid
            ),
            None,
        )
        if turn is None:  # the parent message a thread opens on lives elsewhere
            self.notify(
                "That message belongs to the conversation it branched from.",
                severity="warning",
            )
            return
        if turn.role == "command":
            self.notify(
                "That is a command's output, not a message — rerun the command "
                "instead.",
                severity="warning",
            )
            return
        self.editor = TextArea(turn.text, id="editor")
        target.parent.mount(self.editor, after=target)
        self.editing = target
        target.display = False
        self.editor.focus()
        pane.composer.refresh_hint("rewriting · ctrl+s to save · escape to cancel")

    def action_save_edit(self) -> None:
        if self.editor is None:
            return
        pane = self.pane
        conversation = pane.conversation
        new_text, uuid = self.editor.text, self.editing.uuid
        self.editor.remove()
        self.editor = None

        if uuid.startswith("pending:"):
            # Not in the transcript yet — the edit that happens *before* the
            # model has ever seen the output.
            try:
                if new_text.strip():
                    conversation.edit_pending(uuid, new_text)
                else:
                    conversation.drop_pending(uuid)  # emptied it: drop it
            except Exception as exc:
                self.notify(f"Edit failed: {exc}", severity="error")
            self.run_worker(self._after_edit(pane))
            return

        edited = next((t for t in conversation.turns if t.uuid == uuid), None)
        if edited is not None and edited.role == "user":
            # A rewritten question needs answering again; a rewritten reply does not.
            self.resend(pane, uuid, new_text)
            return

        known = {node.id for node in conversation.root.walk()}
        try:
            dropped = conversation.edit(uuid, new_text)
        except Exception as exc:
            self.notify(f"Edit failed: {exc}", severity="error")
            self.run_worker(self._after_edit(pane))
            return
        note = f" — dropped {dropped} later message(s)" if dropped else ""
        self.notify(f"Message replaced{note}. The AI will only see this version.")
        self._report_thread_fallout(conversation, known)
        self.registry.save(conversation)
        self.run_worker(self._after_edit(pane))

    def _report_thread_fallout(self, conversation, known: set[str]) -> None:
        """An edit can take threads with it; losing one silently would be worse.

        Empty threads hanging off a discarded message are pruned by the core —
        they had nothing left to branch from. Threads that hold real work are
        kept, but nothing in the transcript points at them any more, so say so
        rather than letting them vanish from the screen.
        """
        pruned = known - {node.id for node in conversation.root.walk()}
        if pruned:
            self.notify(
                f"{len(pruned)} empty thread(s) dropped — the message they "
                "branched from is gone.",
                severity="warning",
            )
        orphaned = conversation.orphaned_threads()
        if orphaned:
            self.notify(
                f"{len(orphaned)} thread(s) no longer hang off this "
                "conversation, but keep their messages — ctrl+x to export them.",
                severity="warning",
            )
        # The pane may be showing a thread that has just been pruned.
        if self.thread is not None and self.thread.id in pruned:
            self.thread = None
            self.active = "main"

    async def _after_edit(self, pane: ConversationPane) -> None:
        await self.refresh_all()
        pane.composer.focus_input()

    @work
    async def resend(self, pane: ConversationPane, uuid: str, new_text: str) -> None:
        pane.composer.set_busy(True)
        await pane.draw(pending=True)
        # Resending truncates too, so it can strand threads exactly as edit does.
        known = {node.id for node in pane.conversation.root.walk()}
        failed = None
        try:
            await pane.conversation.edit_and_resend(uuid, new_text)
        except Exception as exc:
            failed = exc
        finally:
            self.registry.save(pane.conversation)
            self._report_thread_fallout(pane.conversation, known)
            await self.refresh_all()
            pane.composer.set_busy(False)
            if failed is not None:
                self.report_failure("Resend failed", failed)
            else:
                self.notify("Question replaced — the AI answered the new version.")
            pane.composer.focus_input()

    async def action_cancel_edit(self) -> None:
        """Escape: out of the editor, or out of the thread."""
        if self.editor is not None:
            self.editor.remove()
            self.editor = None
            self.editing.display = True
            self.pane.composer.focus_input()
            self.pane.composer.refresh_hint()
            return
        await self.close_thread()

    def action_export(self) -> None:
        if self.conversation is None:
            return
        try:
            path = self.conversation.export()
        except Exception as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return
        self.notify(f"Exported to {path} (also exports/latest.md)")

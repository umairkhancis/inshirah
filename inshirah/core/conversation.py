"""Conversation state, with in-place editing of the last AI reply.

History lives in a :class:`TranscriptStore`. Editing a reply mutates the stored
transcript and resumes the *same* session id — the model is handed the edited
text and never sees what it originally wrote.

Forking (branching a conversation at an arbitrary message) is a separate
concern and deliberately not used here: a fork would create a new session id,
which is duplication, not an in-place edit.

A tree of these is a durable object: it has a name that never changes (``id``),
it serializes the turns run against it, and its whole state round-trips through
``dump()``/``restore()``. The tree is the unit, not the individual thread —
threads share one :class:`TranscriptStore` and a thread's first message resumes
its *parent's* session, so the tree is the smallest thing that is internally
consistent. Splitting it would mean coordinating across objects on every branch.

Clients address a thread as (tree id, thread id); see :mod:`inshirah.core.registry`.
"""

import asyncio
import pathlib
import time
import uuid as uuidlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from .config import PROVIDER, PROVIDER_NAME
from .harness import Harness
from .environment import Environment
from . import shell, usage
from .commands import SlashCommand, parse as parse_commands
from .errors import (
    ConversationBusy,
    MessageNotFound,
    NothingToEdit,
    SendFailed,
    failure_of,
)
from .store import TranscriptStore, presentation, summarize_tool, text_of, tool_calls_of



@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str
    uuid: str  # transcript entry id — the handle for editing this turn
    tools: tuple[str, ...] = ()  # tools this turn ran, e.g. ("Read(x.py)",)


class Conversation:
    """One thread: a linear conversation that can be edited and branched.

    A thread started from a message sees the conversation only up to that
    message — not what came after it in the parent, and never anything said in
    the thread itself. Branching uses ``resume_session_at`` + ``fork_session``,
    which slices history at the parent message and gives the thread its own
    session, leaving the parent untouched.
    """

    def __init__(
        self,
        store: TranscriptStore | None = None,
        parent: "Conversation | None" = None,
        branch_point: str | None = None,
        id: str | None = None,
        harness: Harness | None = None,
        can_use_tool: Any = None,
        name: str | None = None,
    ) -> None:
        # The name a client addresses this thread by. Deliberately not
        # ``session_id``: that is None until the first message lands, it is the
        # provider's to choose, and edit_and_resend can replace it mid-life — so
        # it can never appear in a URL. This id is assigned once and never moves.
        self.id = id or uuidlib.uuid4().hex
        # How much of Claude Code is switched on. Threads inherit it: a thread
        # is the same session under a different slice of history, not a
        # different agent.
        self.harness = harness or (parent.harness if parent else Harness())
        # Where an "ask" decision goes. Without one the SDK raises
        # "canUseTool callback is not provided" mid-turn, so a client running
        # any mode that can prompt must supply this.
        self.can_use_tool = can_use_tool or (parent.can_use_tool if parent else None)
        # What a *conversation* is called, as opposed to what a thread is called.
        # Only meaningful on a root: threads are named by what they hang off
        # (``title``), conversations by what they are about. None means "derive
        # it from the first thing asked", so a new conversation needs no naming
        # ceremony before it can be used.
        self.name: str | None = name
        # When this tree last changed, so a list of conversations can put the
        # one you were just in at the top.
        self.updated: float = time.time()
        self.session_id: str | None = None
        self.turns: list[Turn] = []
        self.store = store or TranscriptStore()  # shared by every thread
        self.parent = parent
        self.branch_point = branch_point  # uuid of the message this hangs off
        self.inherited = 0  # messages copied from the parent when branching
        # `!command` output waiting to go with the next prompt; see run_shell.
        self.pending: list[str] = []
        self.threads: dict[str, "Conversation"] = {}

        if parent is None:
            # Tree-wide state, held by the root and reached through ``self.root``.
            # One lock: the whole tree shares a transcript, so two turns anywhere
            # in it must not interleave.
            self._lock = asyncio.Lock()
            self._index: dict[str, "Conversation"] = {}
            # What Claude Code resolved in this directory — skills, agents,
            # MCP servers, memory. Known only once a turn has started.
            self._environment: Environment | None = None
            # The slash commands this project offers, as the CLI reports them.
            # Refreshed on every turn, so a command added to .claude/commands
            # mid-session shows up without a restart.
            self._commands: tuple[SlashCommand, ...] = ()
        self.root._index[self.id] = self
        # A conversation being started, as opposed to one being rehydrated:
        # ``restore`` passes back the id it saved, so an id supplied here
        # means this tree already existed and was counted when it did.
        if parent is None and id is None:
            usage.record("conversations")

    def thread_for(self, uuid: str) -> "Conversation":
        """The thread hanging off a message, created on first use."""
        # Deliberately not guarded by ``busy``: branching adds a node and reads
        # turns, it never writes the transcript, so it is safe mid-turn — and
        # the TUI lets you open a thread while a reply is still coming back.
        if uuid not in self.threads:
            thread = Conversation(self.store, parent=self, branch_point=uuid)
            # The fork copies the parent up to and including this message, so
            # that many messages are inherited rather than said in the thread.
            uuids = [t.uuid for t in self.turns]
            thread.inherited = uuids.index(uuid) + 1 if uuid in uuids else 0
            self.threads[uuid] = thread
            usage.record("threads")
        return self.threads[uuid]

    @property
    def root(self) -> "Conversation":
        return self if self.parent is None else self.parent.root

    @property
    def environment(self) -> Environment | None:
        """What this project loaded, or None until the first turn has run."""
        return self.root._environment

    @property
    def commands(self) -> tuple[SlashCommand, ...]:
        """The slash commands available here; empty until something has asked."""
        return self.root._commands

    def offer_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        """Record what a client learned by asking the CLI directly."""
        if commands:
            self.root._commands = commands

    @property
    def busy(self) -> bool:
        """Is a turn running anywhere in this tree?"""
        return self.root._lock.locked()

    def thread(self, thread_id: str) -> "Conversation":
        """Resolve a thread id anywhere in this tree — the (tree, thread) address.

        A client holds ids across requests where the TUI holds object
        references, so this is the lookup that replaces ``self.conversation =
        self.conversation.thread_for(uuid)``.
        """
        node = self.root._index.get(thread_id)
        if node is None:
            raise MessageNotFound(f"no thread {thread_id!r} in this conversation")
        return node

    def walk(self) -> "list[Conversation]":
        """This thread and every thread beneath it, depth-first."""
        found = [self]
        for child in self.threads.values():
            found.extend(child.walk())
        return found

    def _branch_context(self) -> "tuple[list[Turn], int] | None":
        """Where to read the message this thread hangs off, and at what index.

        Once the thread has started it holds its *own* copy of that message —
        the fork copied it in, and that copy is what the model in this thread
        actually sees. The parent's copy can have been rewritten since, or
        discarded altogether by an edit further up; reading the parent would
        then show a version this thread has never been told about.

        Before the thread starts there is no own copy, and the parent's is both
        the only one and the one the fork is about to capture.
        """
        if self.parent is None or self.branch_point is None:
            return None
        inherited = min(self.inherited, len(self.turns))
        if inherited:
            return self.turns, inherited - 1
        uuids = [t.uuid for t in self.parent.turns]
        if self.branch_point not in uuids:
            return None
        return self.parent.turns, uuids.index(self.branch_point)

    @property
    def branch_turn(self) -> "Turn | None":
        """The message this thread hangs off, as this thread has it."""
        found = self._branch_context()
        return None if found is None else found[0][found[1]]

    def title(self, width: int = 40) -> str:
        """What this thread hangs off, named by the question that prompted it.

        ``width`` only trims; every client names a thread the same way, so a
        breadcrumb and an export cannot disagree about what a thread is called.
        """
        if self.parent is None:
            return "main"
        found = self._branch_context()
        if found is None:
            return "thread"
        turns, index = found
        turn = turns[index]
        if turn.role == "assistant":
            earlier = [t for t in turns[:index] if t.role == "user"]
            turn = earlier[-1] if earlier else turn
        return " ".join(turn.text.split())[:width] or "thread"

    def display_name(self, width: int = 32) -> str:
        """What to call this conversation in a list of conversations.

        Deliberately separate from ``title``: that answers "what does this
        thread hang off", which is a question about a branch. This answers "what
        is this conversation about", which is a question about the whole tree —
        and every thread in a tree answers it the same way, because they are all
        in the same conversation.
        """
        root = self.root
        if root.name:
            return root.name[:width]
        for turn in root.turns:
            # A slash command or a shell line says what you did, not what the
            # conversation is about — naming it "/config" helps nobody.
            if turn.role != "user" or not turn.text.strip():
                continue
            if turn.text.startswith(("/", "$ ")):
                continue
            return " ".join(turn.text.split())[:width]
        return "New conversation"

    def breadcrumb(self, width: int = 24) -> list[str]:
        """``["main", …]`` — the path from the root down to this thread."""
        parts, node = [], self
        while node.parent is not None:
            parts.append(node.title(width))
            node = node.parent
        return ["main", *reversed(parts)]

    def reply_count(self, uuid: str) -> int:
        """How many replies a thread holds — not how much context it carries.

        ``own_turns``, so the "N replies" offered on a message and the "N
        replies" shown inside the thread cannot disagree.
        """
        thread = self.threads.get(uuid)
        return len(thread.own_turns) if thread else 0

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def _options(self) -> ClaudeAgentOptions:
        """The options for one turn.

        Everything that decides *how much Claude Code* is running comes from
        ``self.harness`` — the preset prompt, the tool suite, settings sources
        and the project directory. Inshirah does not reimplement any of it; the
        point of this app is the surface, not a second agent underneath it.
        """
        options = ClaudeAgentOptions(
            **self.harness.options(),
            can_use_tool=self.can_use_tool,
            model=PROVIDER.model,
            env=PROVIDER.env,
            resume=self.session_id,
            session_store=self.store,
        )
        if self.session_id is None and self.parent is not None:
            # First message in a thread: branch the parent at our message. The
            # parent keeps its own session, so the branch is non-destructive.
            options.resume = self.parent.session_id
            options.resume_session_at = self.branch_point
            options.fork_session = True
        return options

    async def run_shell(self, command: str) -> Turn:
        """Run ``!command`` and hold its output for the next message.

        The output is *not* injected into the stored transcript. Claude Code's
        transcript is a ``parentUuid``-linked chain with a ``last-prompt`` entry
        pointing at its leaf; an entry appended outside that chain is an orphan
        and the CLI ignores it — verified, the model saw nothing. Writing a
        well-formed link would mean maintaining Claude Code's private format,
        which is exactly what this app set out not to do.

        So shell output waits in ``pending`` and goes with the next prompt. That
        turns out to be the better surface anyway: it is editable *before* the
        model has ever seen it, which is the whole point of piping a build log in
        and cutting it to the three lines that matter.
        """
        if self.busy:
            raise ConversationBusy("a turn is running; wait for it to finish")
        result = await shell.run(command, self.harness.project)
        self.pending.append(result.as_message())
        usage.record("shell_holds")
        return Turn("user", result.as_message(), f"pending:{len(self.pending) - 1}")

    def edit_pending(self, handle: str, new_text: str) -> None:
        """Rewrite held shell output before it is ever sent."""
        index = int(handle.removeprefix("pending:"))
        if not 0 <= index < len(self.pending):
            raise MessageNotFound(f"no held output {handle!r}")
        self.pending[index] = new_text

    def drop_pending(self, handle: str) -> None:
        """Discard held output — a command whose result turned out to be noise."""
        index = int(handle.removeprefix("pending:"))
        if not 0 <= index < len(self.pending):
            raise MessageNotFound(f"no held output {handle!r}")
        del self.pending[index]

    @property
    def pending_turns(self) -> list[Turn]:
        """Held shell output, shaped like turns so a client can render it."""
        return [Turn("user", text, f"pending:{i}") for i, text in enumerate(self.pending)]

    def _with_pending(self, prompt: str) -> str:
        """Put held `!command` output in front of the prompt, and clear it.

        Composition, not execution: the model should read the terminal first and
        then the question about it.
        """
        if not self.pending:
            return prompt
        composed = "\n\n".join([*self.pending, prompt])
        self.pending.clear()
        return composed

    async def send(self, prompt: str) -> Turn:
        """Send a user message and record the reply.

        Turns are serialized across the whole tree. The TUI got away without
        this by disabling its input box for the duration; a client that can have
        two requests in flight cannot, and two turns interleaving would write
        each other's entries into one shared transcript.
        """
        async with self.root._lock:
            return await self._run_turn(self._with_pending(prompt))

    async def _run_turn(self, prompt: str) -> Turn:
        """One turn, assuming the tree lock is already held.

        A failed turn is rolled back out of the transcript. The CLI records API
        errors as ordinary assistant messages, so leaving one in place would put
        the error text into the context of every later turn.
        """
        before = len(self.store.entries(self.session_id or ""))
        failure: str | None = None
        async with ClaudeSDKClient(options=self._options()) as client:
            # Free: the command list arrives with the initialize response, so
            # reading it here keeps it current without costing a turn.
            info = await client.get_server_info()
            if info:
                self.root._commands = parse_commands(info.get("commands"))
            await client.query(prompt)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    self.session_id = message.session_id or self.session_id
                elif isinstance(message, SystemMessage) and message.subtype == "init":
                    # The CLI's account of what it loaded for this directory.
                    self.root._environment = Environment.from_init(message.data)
                elif isinstance(message, ResultMessage) and message.is_error:
                    failure = failure_of(message)

        if failure is not None:
            self.store.rollback(self.session_id or "", before)
            self._sync()
            raise SendFailed(failure)

        self._sync()
        usage.record("turns")
        return self.turns[-1]

    def _sync(self) -> None:
        """Rebuild the visible turns from the store.

        The store is the conversation the model will be given, so deriving the
        UI from it means the two cannot drift apart — and an edit that drops
        later turns is reflected on screen without extra bookkeeping.

        Every transcript change funnels through here, so this is also where the
        tree's activity stamp is kept — ``restore`` puts the saved one back
        afterwards, or loading a conversation would look like using it.
        """
        self.root.updated = time.time()
        self.turns = [
            Turn(
                *presentation(entry),
                entry.get("uuid", ""),
                tuple(summarize_tool(c) for c in tool_calls_of(entry)),
            )
            for entry in self.store.messages(self.session_id or "")
        ]

    def prune_unstartable_threads(self) -> list[str]:
        """Drop empty threads whose branch point an edit has discarded.

        An edit truncates everything after the message it rewrites. A thread
        hanging off a discarded message has nothing left to branch from: it
        would resume the parent at a uuid the transcript no longer holds. While
        it is still empty there is nothing to lose by dropping it — a thread
        that has already been used is kept, because its own session stands on
        its own and its content is real work.

        Returns the ids dropped, so a client can say what happened.
        """
        alive = {turn.uuid for turn in self.turns}
        gone = [
            uuid
            for uuid, thread in self.threads.items()
            if uuid not in alive and not thread.turns
        ]
        for uuid in gone:
            thread = self.threads.pop(uuid)
            for node in thread.walk():
                self.root._index.pop(node.id, None)
        return gone

    def orphaned_threads(self) -> list["Conversation"]:
        """Threads still holding work whose branch point has been edited away.

        They keep their transcript and still appear in an export, but nothing in
        the parent points at them any more.
        """
        alive = {turn.uuid for turn in self.turns}
        return [t for uuid, t in self.threads.items() if uuid not in alive and t.turns]

    @property
    def own_turns(self) -> list[Turn]:
        """The turns said *in* this thread, without the ancestors it inherited.

        A thread's session is a fork of its parent sliced at the branch point, so
        its transcript legitimately begins with everything up to that message —
        that is the context the model needs, and it must stay in ``turns``. It is
        not what a reader needs: they opened a thread off one message precisely
        so they would not have to read the conversation again inside it.

        The main conversation inherits nothing, so this is simply ``turns``
        there — which is why a client can render this and never special-case the
        root.
        """
        return self.turns[min(self.inherited, len(self.turns)) :]

    @property
    def last_response(self) -> Turn | None:
        last = self.turns[-1] if self.turns else None
        return last if last and last.role == "assistant" else None

    def edit(self, uuid: str, new_text: str) -> int:
        """Rewrite any message; returns how many later turns were discarded."""
        if self.session_id is None:
            raise NothingToEdit("nothing to edit yet")
        if self.busy:
            raise ConversationBusy("a turn is running; cannot edit right now")
        # Read before the rewrite: ``_sync`` rebuilds ``turns`` from the
        # store, and whose message this was is the half of the count worth
        # having.
        role = next((t.role for t in self.turns if t.uuid == uuid), "")
        dropped = self.store.edit(self.session_id, uuid, new_text)
        if dropped < 0:
            raise MessageNotFound("message not found in the stored transcript")
        self._sync()
        self.prune_unstartable_threads()
        usage.record_edit(role)
        return dropped

    async def edit_and_resend(self, uuid: str, new_text: str) -> Turn:
        """Rewrite a question and ask the model to answer the new version.

        Editing a reply replaces what the model said, so there is nothing to
        re-answer. Editing a question is different: the answer that followed no
        longer belongs to it, so the question and everything after it are
        dropped and the new wording is sent as a fresh turn.
        """
        if self.session_id is None:
            raise NothingToEdit("nothing to resend yet")
        async with self.root._lock:
            turn = await self._resend(uuid, new_text)
        usage.record_edit("user")
        usage.record("resends")
        return turn

    async def _resend(self, uuid: str, new_text: str) -> Turn:
        """Truncate and re-ask as one indivisible turn — the lock is held."""
        if self.store.truncate(self.session_id or "", uuid) < 0:
            raise MessageNotFound("message not found in the stored transcript")
        if not self.store.messages(self.session_id):
            # Nothing visible survived — the whole conversation was replaced.
            # Non-message lines can remain, and resuming a session that holds
            # only those fails with "No conversation found", so drop it entirely.
            self.store.rollback(self.session_id, 0)
            self.session_id = None
        self.inherited = min(self.inherited, len(self.store.messages(self.session_id or "")))
        self._sync()
        self.prune_unstartable_threads()
        return await self._run_turn(self._with_pending(new_text))

    def edit_last_response(self, new_text: str) -> int:
        target = self.last_response
        if target is None:
            raise NothingToEdit("no editable response yet")
        return self.edit(target.uuid, new_text)

    # --- serialization ----------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Everything a client needs to render this thread, as plain JSON.

        The read model. Without it every client re-derives the same things from
        the object graph — the TUI already computes reply counts and a
        breadcrumb by hand — and they drift. ``turns`` is what to draw,
        ``threads`` is where you can drill in, and both carry the ids the write
        endpoints take back.
        """
        return {
            "id": self.id,
            "title": self.title(),
            "breadcrumb": self.breadcrumb(),
            "depth": self.depth,
            "parent_id": self.parent.id if self.parent else None,
            "branch_point": self.branch_point,
            "session_id": self.session_id,
            "started": self.session_id is not None,
            "busy": self.busy,
            "inherited": min(self.inherited, len(self.turns)),
            "turns": [
                {
                    "uuid": turn.uuid,
                    "role": turn.role,
                    "text": turn.text,
                    "tools": list(turn.tools),
                    "replies": self.reply_count(turn.uuid),
                    "thread_id": t.id if (t := self.threads.get(turn.uuid)) else None,
                    "inherited": position < min(self.inherited, len(self.turns)),
                }
                for position, turn in enumerate(self.turns)
            ],
            "threads": [
                {
                    "id": thread.id,
                    "title": thread.title(),
                    "branch_point": thread.branch_point,
                    "messages": len(thread.own_turns),
                }
                for thread in self.threads.values()
            ],
        }

    def tree_snapshot(self) -> dict[str, Any]:
        """Every thread in the tree, root first — one round trip for a whole UI."""
        return {
            "id": self.root.id,
            "busy": self.busy,
            "threads": [thread.snapshot() for thread in self.root.walk()],
        }

    # --- durability -------------------------------------------------------
    #
    # What makes this a durable object rather than a merely addressable one.
    # ``dump()`` is the complete state: the shared transcript plus the shape of
    # the tree. Ids survive the round trip, so a client's saved links still
    # resolve after a restart.

    def dump(self) -> dict[str, Any]:
        """The whole tree, as JSON. Call on any node; always dumps the root."""
        root = self.root

        def node(conversation: "Conversation") -> dict[str, Any]:
            return {
                "id": conversation.id,
                "session_id": conversation.session_id,
                "branch_point": conversation.branch_point,
                "inherited": conversation.inherited,
                "threads": {
                    uuid: node(child)
                    for uuid, child in conversation.threads.items()
                },
            }

        return {
            "version": 1,
            "name": root.name,
            "updated": root.updated,
            "transcripts": root.store.dump(),
            "tree": node(root),
        }

    @classmethod
    def restore(cls, data: dict[str, Any]) -> "Conversation":
        """Rebuild a tree that ``dump()`` wrote, ids and all."""
        store = TranscriptStore()
        store.restore(data.get("transcripts", {}))

        def node(state: dict[str, Any], parent: "Conversation | None") -> "Conversation":
            conversation = cls(
                store,
                parent=parent,
                branch_point=state.get("branch_point"),
                id=state.get("id"),
            )
            conversation.session_id = state.get("session_id")
            conversation.inherited = state.get("inherited", 0)
            conversation._sync()
            for uuid, child in (state.get("threads") or {}).items():
                conversation.threads[uuid] = node(child, conversation)
            return conversation

        tree = node(data["tree"], None)
        tree.name = data.get("name")
        # After the _sync calls above, which stamped it as "just now".
        tree.updated = data.get("updated", tree.updated)
        return tree

    def render_export(self) -> str:
        """Every thread and the exact context each one sends to the model.

        The whole tree is rendered, not just the thread on screen, so the two
        isolation properties can be checked by reading one document: a thread
        sees its ancestors but nothing said after the branch point, and the
        parent never sees anything said inside a thread.

        Returns the markdown rather than a path, because a client that serves a
        download has nowhere to put a file — ``export()`` below is the wrapper
        for the one that does.
        """
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        threads = self.root.walk()

        lines = [
            f"# Inshirah conversation — {stamp}",
            "",
            f"- provider: `{PROVIDER_NAME}`",
            f"- model: `{PROVIDER.model or 'CLI default'}`",
            f"- viewing: **{self.title()}**",
            "",
            "## Threads",
            "",
            "Each thread is a separate session. `inherited` messages were copied",
            "from the parent when the thread branched; the rest were sent here.",
            "",
            "| thread | session | inherited | sent here | total context |",
            "| --- | --- | --- | --- | --- |",
        ]
        for thread in threads:
            total = len(thread.turns)
            inherited = min(thread.inherited, total)  # nothing is inherited until it starts
            lines.append(
                f"| {'&nbsp;&nbsp;' * thread.depth}{thread.title()} "
                f"| `{thread.session_id or 'not started'}` "
                f"| {inherited} | {total - inherited} | {total} |"
            )

        for thread in threads:
            lines += [
                "",
                f"## Context sent to the model — {thread.title()}",
                "",
                f"- session: `{thread.session_id or 'not started'}`",
                f"- branched from: "
                + (f"**{thread.parent.title()}** at message `{thread.branch_point}`"
                   if thread.parent else "_nothing — this is the main conversation_"),
                "",
            ]
            if not thread.turns:
                lines += ["_empty — nothing sent in this thread yet._", ""]
                continue
            inherited = min(thread.inherited, len(thread.turns))
            for position, turn in enumerate(thread.turns):
                origin = "inherited" if position < inherited else "sent here"
                lines += [f"### {position + 1}. {turn.role} ({origin})", "", turn.text, ""]

        return "\n".join(lines)

    def export(self, directory: str = "exports") -> pathlib.Path:
        """Write :meth:`render_export` to a timestamped file; returns the path."""
        out = pathlib.Path(directory)
        out.mkdir(exist_ok=True)
        text = self.render_export()
        path = out / f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(text)
        (out / "latest.md").write_text(text)  # stable path, easy to reference
        usage.record("exports")
        return path

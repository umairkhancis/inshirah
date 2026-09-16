"""Addressing and durability for conversation trees.

A client holds ids across requests where the TUI holds object references, so
something has to turn an id back into the live object. That is this module:

    registry = ConversationRegistry(FileStorage("~/.inshirah/conversations"))
    tree     = registry.create()                  # a new conversation
    tree     = registry.get(tree_id)              # live, or rehydrated from disk
    thread   = registry.thread(tree_id, thread_id)  # any thread within it

Exactly one live tree per id, so the lock inside it actually means something —
two registries over one directory would each hold their own copy and overwrite
each other. Treat the registry as process-wide.

Persisting is explicit (``save``) rather than automatic on every mutation: a
turn touches the transcript repeatedly while it streams, and writing the whole
tree each time would be wasteful. Clients save at the end of a turn.
"""

import json
import pathlib
from typing import Any, Protocol

from .conversation import Conversation
from .errors import ConversationNotFound
from .harness import Harness


class Storage(Protocol):
    """Where a tree's ``dump()`` goes when nothing is holding it in memory."""

    def save(self, tree_id: str, data: dict[str, Any]) -> None: ...

    def load(self, tree_id: str) -> dict[str, Any] | None: ...

    def ids(self) -> list[str]: ...

    def delete(self, tree_id: str) -> None: ...


class MemoryStorage:
    """The default — durable for the life of the process, and no further.

    What the TUI has always had. Enough for a single-process web server; swap in
    :class:`FileStorage` the moment a restart must not lose conversations.
    """

    def __init__(self) -> None:
        self._trees: dict[str, dict[str, Any]] = {}

    def save(self, tree_id: str, data: dict[str, Any]) -> None:
        self._trees[tree_id] = data

    def load(self, tree_id: str) -> dict[str, Any] | None:
        return self._trees.get(tree_id)

    def ids(self) -> list[str]:
        return list(self._trees)

    def delete(self, tree_id: str) -> None:
        self._trees.pop(tree_id, None)


class FileStorage:
    """One JSON file per tree. Survives a restart."""

    def __init__(self, directory: str | pathlib.Path) -> None:
        self.directory = pathlib.Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, tree_id: str) -> pathlib.Path:
        return self.directory / f"{tree_id}.json"

    def save(self, tree_id: str, data: dict[str, Any]) -> None:
        # Write beside the target and rename, so a crash mid-write leaves the
        # previous conversation intact rather than a truncated file.
        temporary = self._path(tree_id).with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(self._path(tree_id))

    def load(self, tree_id: str) -> dict[str, Any] | None:
        path = self._path(tree_id)
        return json.loads(path.read_text()) if path.exists() else None

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def delete(self, tree_id: str) -> None:
        self._path(tree_id).unlink(missing_ok=True)


class ConversationRegistry:
    """The namespace: id → the one live conversation tree with that id.

    The harness and the permission callback are held here rather than passed at
    every call, because they are properties of the *session* — which project is
    open, and where an "ask" decision goes — not of any one conversation. A tree
    rehydrated from disk gets them too, or a conversation resumed after a
    restart would run with no tools and no way to prompt.
    """

    def __init__(
        self,
        storage: Storage | None = None,
        harness: Harness | None = None,
        can_use_tool: Any = None,
    ) -> None:
        self.storage = storage or MemoryStorage()
        self.harness = harness or Harness()
        self.can_use_tool = can_use_tool
        self._live: dict[str, Conversation] = {}

    def create(self, name: str | None = None) -> Conversation:
        tree = Conversation(
            harness=self.harness, can_use_tool=self.can_use_tool, name=name
        )
        self._live[tree.id] = tree
        self.save(tree)
        return tree

    def get(self, tree_id: str) -> Conversation:
        """The live tree, rehydrated from storage if it is not in memory."""
        if tree_id in self._live:
            return self._live[tree_id]
        data = self.storage.load(tree_id)
        if data is None:
            raise ConversationNotFound(f"no conversation {tree_id!r}")
        tree = Conversation.restore(data)
        self._adopt(tree)
        self._live[tree_id] = tree
        return tree

    def _adopt(self, tree: Conversation) -> None:
        """Give a restored tree this session's harness and permission prompt.

        ``restore`` rebuilds the shape and the transcript; it cannot know which
        project is open or which app is asking, so every node is handed them
        here — threads included, since any of them can run a turn.
        """
        for node in tree.walk():
            node.harness = self.harness
            node.can_use_tool = self.can_use_tool

    def rename(self, tree_id: str, name: str | None) -> Conversation:
        """Name a conversation explicitly; None goes back to the derived name."""
        tree = self.get(tree_id)
        tree.name = name.strip() if name and name.strip() else None
        self.save(tree)
        return tree

    def listing(self) -> list[dict[str, Any]]:
        """Every conversation, most recently used first — what a sidebar draws.

        Each tree is materialised to read its name and size. That is fine at the
        scale a person accumulates conversations, and it keeps one definition of
        what a conversation is called; if this ever gets slow, the fix is a
        summary written alongside the dump, not a second naming rule here.
        """
        summaries = []
        for tree_id in self.ids():
            try:
                tree = self.get(tree_id)
            except ConversationNotFound:  # deleted between listing and loading
                continue
            summaries.append(
                {
                    "id": tree.id,
                    "name": tree.display_name(),
                    "named": tree.name is not None,
                    "messages": len(tree.turns),
                    "threads": len(tree.walk()) - 1,
                    "updated": tree.updated,
                    "busy": tree.busy,
                }
            )
        return sorted(summaries, key=lambda s: s["updated"], reverse=True)

    def thread(self, tree_id: str, thread_id: str | None = None) -> Conversation:
        """Resolve a (tree, thread) address; no thread id means the root."""
        tree = self.get(tree_id)
        return tree if thread_id in (None, tree_id) else tree.thread(thread_id)

    def save(self, tree: Conversation) -> None:
        self.storage.save(tree.root.id, tree.dump())

    def delete(self, tree_id: str) -> None:
        self._live.pop(tree_id, None)
        self.storage.delete(tree_id)

    def ids(self) -> list[str]:
        """Every tree this registry knows of, live or stored."""
        return sorted({*self._live, *self.storage.ids()})

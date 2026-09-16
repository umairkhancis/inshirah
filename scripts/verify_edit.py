"""Check that an edited message — and only the edited message — reaches the model.

A valid test needs a fact that exists in exactly ONE message, was invented by the
AI, and has no correct answer. If the fact also appears in a user turn, or has a
verifiable truth, the model will reason past the edit and the test proves nothing.

Run it as a module from the repo root, so that ``inshirah`` is importable —
``python scripts/verify_edit.py`` puts *scripts/* on the path, not the root:

    python -m scripts.verify_edit                          # default provider
    INSHIRAH_PROVIDER=anthropic python -m scripts.verify_edit
"""

import asyncio
import sys

from inshirah.core import PROVIDER_NAME, Conversation

SENTINEL = "Zorblat"  # implausible as a spontaneous answer


async def main() -> int:
    c = Conversation()

    await c.send("Invent a one-word codename for a project. Reply with just the word.")
    original = c.turns[-1].text.strip()
    target = c.turns[-1].uuid
    print(f"1. AI invented      : {original!r}")

    dropped = c.edit(target, SENTINEL)
    print(f"2. Edited to        : {SENTINEL!r} (dropped {dropped} later message(s))")

    context = [t.text for t in c.turns]
    mechanism = any(SENTINEL in t for t in context) and not any(original in t for t in context)
    print(f"3. Context check    : {'PASS' if mechanism else 'FAIL'} "
          f"— stored context {'holds only the edit' if mechanism else 'still shows the original'}")

    await c.send("What is the codename? Reply with just the word.")
    answer = c.turns[-1].text.strip()
    print(f"4. AI now answers   : {answer!r}")

    behaviour = SENTINEL.lower() in answer.lower() and original.lower() not in answer.lower()
    print(f"5. Behaviour check  : {'PASS' if behaviour else 'FAIL'}")

    ok = mechanism and behaviour
    print(f"\n[{PROVIDER_NAME}] {'PASS — the AI sees only the edited message' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

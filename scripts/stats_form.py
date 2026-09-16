#!/usr/bin/env python3
"""Turn a Google Forms pre-filled link into the two constants ``share`` needs.

    python scripts/stats_form.py 'https://docs.google.com/forms/d/e/1FA.../viewform?usp=pp_url&entry.123=edits&...'

The form has one short-answer question per payload key. Google names those
questions ``entry.<digits>`` and there is no way to see the number in the
editor, so the way to read them off is to ask the form for a pre-filled link
with a known value in every box — and the trick that makes this a script rather
than an afternoon is to fill each box with *the name of the key it is for*. The
link then already contains the mapping, and this reads it back out.

See docs/stats-form.md for the ten minutes of clicking that produces the link.

Deliberately dependency-free and outside the package: nothing here ships to a
user, and ``tests/test_privacy.py`` only governs ``inshirah/``.
"""

import re
import sys
from urllib.parse import parse_qsl, urlparse

from inshirah.core import usage

FORM_ID = re.compile(r"/forms/d/e/([^/]+)/")


def parse(link: str) -> tuple[str, dict[str, str]]:
    match = FORM_ID.search(link)
    if not match:
        raise SystemExit("that does not look like a Google Forms link: no /d/e/<id>/")
    fields = {
        value: name
        for name, value in parse_qsl(urlparse(link).query)
        if name.startswith("entry.")
    }
    return match.group(1), fields


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    form_id, fields = parse(argv[1])
    expected = set(usage.summary())

    unknown = set(fields) - expected
    missing = expected - set(fields)
    if unknown:
        print(f"! not a payload key, so it will never be filled in: {sorted(unknown)}")
        print("  (did you type the key name as the value in every box?)\n")
    if missing:
        print(f"! no question on the form for: {sorted(missing)}")
        print("  (these are simply not collected — add the questions to change that)\n")

    print("Paste into inshirah/core/share.py:\n")
    print(f'FORM_ID = "{form_id}"\n')
    print("FIELDS = {")
    for key in usage.summary():  # declared order, not the form's
        if key in fields:
            print(f'    "{key}": "{fields[key]}",')
    print("}")
    return 1 if (unknown or missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

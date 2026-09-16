"""Inshirah — entry point for the terminal client.

Equivalent to ``python -m inshirah.tui``; kept so ``python main.py`` still works.
Run ``python main.py --help`` for the flags that narrow what the agent may do.
"""

from inshirah.tui.__main__ import main

if __name__ == "__main__":
    main()

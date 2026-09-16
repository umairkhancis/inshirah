"""Provider config — switch the whole app between backends with one env var.

    python main.py "hello"                             # ollama (default)
    INSHIRAH_PROVIDER=anthropic python main.py "hello" # Claude

Claude Code talks the Anthropic Messages API; Ollama 0.14.0+ serves that API
natively, so switching backends is purely a matter of pointing the CLI at a
different base URL. No translation layer involved.

Note: run the Ollama server with OLLAMA_CONTEXT_LENGTH=32768 (or higher) —
Claude Code's system prompt does not fit in the 4096-token default.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    model: str | None = None  # None = whatever the CLI defaults to
    env: dict[str, str] = field(default_factory=dict)


# must be a model `ollama list` shows; upgrade to gpt-oss:20b once pulled
_OLLAMA_MODEL = os.getenv("INSHIRAH_MODEL", "llama3.2:latest")

PROVIDERS = {
    "anthropic": Provider(),
    "ollama": Provider(
        model=_OLLAMA_MODEL,
        env={
            "ANTHROPIC_BASE_URL": "http://localhost:11434",
            "ANTHROPIC_AUTH_TOKEN": "ollama",
            "ANTHROPIC_API_KEY": "",  # don't forward a real key to a local server
            # side tasks (session titles etc.) would otherwise ask for a Claude model
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": _OLLAMA_MODEL,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": _OLLAMA_MODEL,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": _OLLAMA_MODEL,
            "ANTHROPIC_SMALL_FAST_MODEL": _OLLAMA_MODEL,
        },
    ),
}

PROVIDER_NAME = os.getenv("INSHIRAH_PROVIDER", "anthropic")
PROVIDER = PROVIDERS[PROVIDER_NAME]

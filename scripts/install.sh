#!/bin/sh
# Inshirah installer — macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/umairkhancis/inshirah/main/scripts/install.sh | sh
#
# Short on purpose. Piping a script from the internet into a shell is a thing
# thoughtful people are right to dislike, and this one asks to be read first: it
# installs uv if it is missing, installs Inshirah with it, and prints what to do
# next. No sudo, nothing outside your home directory, no data sent anywhere.
set -eu

UV_INSTALLER="https://astral.sh/uv/install.sh"
BIN="$HOME/.local/bin"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

fetch() {
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- "$1"
    else
        die "need curl or wget to download anything"
    fi
}

# uv, because it is the one tool that also solves Python itself: it fetches a
# suitable interpreter when the machine has none, so this does not have to ask
# anyone to install Python 3.12 first.
if command -v uv >/dev/null 2>&1; then
    say "uv: already installed"
else
    say "uv: installing (Inshirah is a Python tool; uv is what puts it on PATH)"
    fetch "$UV_INSTALLER" | sh >/dev/null || die "could not install uv"
fi

# A shell that was already open does not have the new PATH, and the installer
# runs in exactly that shell. So resolve it here rather than relying on it.
PATH="$BIN:$PATH"
export PATH
command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH; open a new shell and re-run"

say "inshirah: installing"
uv tool install --upgrade inshirah >/dev/null || die "could not install inshirah"
uv tool update-shell >/dev/null 2>&1 || true   # so a new shell finds it too

INSHIRAH="$(command -v inshirah || echo "$BIN/inshirah")"
"$INSHIRAH" --version >/dev/null 2>&1 || die "installed, but the command does not run"

say ""
say "Installed: $("$INSHIRAH" --version)"
say ""
say "Next:"
say "  inshirah --login     # once, only if you have never signed in to Claude Code"
say "  inshirah             # from any project directory"
say ""
say "It runs on this machine, against your own Claude Code. Nothing is sent"
say "anywhere else — run 'inshirah --privacy' to see exactly what that means."

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) say ""; say "Note: add $BIN to your PATH, or open a new terminal." ;;
esac

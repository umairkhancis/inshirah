# The Homebrew tap

`brew install umairkhancis/tap/inshirah` resolves to `Formula/inshirah.rb` in a
GitHub repo called **`umairkhancis/homebrew-tap`**. This directory holds the
formula that goes into it, versioned alongside the code it installs so the two
cannot drift silently.

Homebrew is second, not first. PyPI is where the formula gets the source from,
so a release goes out in that order.

## Do not run `brew update-python-resources`

It is the obvious tool and it does not work here. Two independent reasons:

1. It passes `--uploaded-prior-to=P1D` to pip, so it cannot see a release
   published in the last 24 hours — which is every release, on release day. It
   fails with "Unable to determine dependencies".

2. It writes **sdist** resources. `pydantic-core`, `rpds-py` and `cryptography`
   would then each need a Rust toolchain to build. Worse, `claude-agent-sdk`'s
   sdist contains no Claude Code binary at all — only `scripts/download_cli.py`,
   which fetches one at build time, and Homebrew builds offline. A source
   install of that package produces an Inshirah that **installs cleanly and
   cannot start a session**, with nothing in the build log to say so.

`scripts/brew_formula.py` exists because of this. It resolves the tree with
pip's own resolver and pins wheels.

## Per release

1. Publish to PyPI first (tag the repo; `.github/workflows/release.yml` does the
   rest). Everything below reads from what PyPI is serving.

2. Regenerate the formula:

   ```sh
   python3 scripts/brew_formula.py <version> > deploy/homebrew/inshirah.rb
   ```

3. Copy it into the tap and check it from a clean prefix:

   ```sh
   cp deploy/homebrew/inshirah.rb "$(brew --repository)/Library/Taps/umairkhancis/homebrew-tap/Formula/inshirah.rb"
   brew uninstall inshirah
   brew install --build-from-source umairkhancis/tap/inshirah
   brew test inshirah
   brew audit --strict --online umairkhancis/tap/inshirah
   ```

4. Verify the bundled binary actually survived — this is the failure the tests
   above do **not** catch, because `--version` and `--privacy` never start a
   session:

   ```sh
   "$(brew --prefix inshirah)/libexec/lib/python3.13/site-packages/claude_agent_sdk/_bundled/claude" --version
   ```

5. Commit and push the tap. `brew install umairkhancis/tap/inshirah` is live as
   soon as the push lands — there is no review queue for a personal tap.

## Three things that will bite the next person

**Homebrew unpacks platform wheels.** It keeps the `.whl` file only when the URL
matches `py3[^-]*-none-any.whl` (`Library/Homebrew/language/python.rb`). Every
other wheel is unpacked into a directory, and pip cannot install an unpacked
wheel as a source tree. The formula's `install` therefore installs those from
`resource(name).cached_download`, copied back to its real filename first —
Homebrew's cache prefixes files with `<sha>--`, which breaks pip's tag parsing.

**The venv has no `pip`.** Homebrew creates it with `--without-pip` and installs
through the external interpreter (`python3.13 -m pip --python=<venv>/bin/python`).
Calling `libexec/"bin/pip"` fails with a file that was never created. Use
`venv.pip_install`.

**A Pathname as the command to `system` hides the error.** If the command fails,
Homebrew crashes serialising the failure (`Pathname not allowed in JSON`,
`utils/fork.rb`) and the real cause never prints. Pass strings.

## Intel Macs

`cryptography` publishes no Intel macOS wheel, so that arch alone builds it from
source; the formula adds `rust` and `openssl@3` as Intel-only dependencies for
it. **This path has never been tested** — it was written on Apple Silicon.

The same gap applies to `scripts/install.sh`: a uv install on an Intel Mac will
also have to compile `cryptography`. If a friend on an Intel machine is the first
to try either installer, watch it with them.

## A note on size

`claude-agent-sdk` ships a bundled Claude Code binary of a couple of hundred
megabytes, so the install lands around 257 MB and takes a while. There is
nothing to be done about it short of dropping the bundle, which would trade a
slow install for a broken first run.

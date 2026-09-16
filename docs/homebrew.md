# The Homebrew tap

`brew install umairkhancis/tap/inshirah` resolves to `Formula/inshirah.rb` in a
GitHub repo called **`umairkhancis/homebrew-tap`**. That repo does not exist
yet; this directory holds the formula that goes into it, versioned alongside the
code it installs so the two cannot drift silently.

Homebrew is second, not first. PyPI is where the formula gets the source from,
so a release goes out in that order.

## Once, to create the tap

```sh
gh repo create umairkhancis/homebrew-tap --public \
  --description "Homebrew formulae for Inshirah"
git clone https://github.com/umairkhancis/homebrew-tap && cd homebrew-tap
mkdir Formula
```

## Per release

1. Publish to PyPI first (tag the repo; `.github/workflows/release.yml` does the
   rest). Homebrew installs from the sdist PyPI serves, not from git.

2. Copy the formula in and point it at that release:

   ```sh
   cp path/to/inshirah/deploy/homebrew/inshirah.rb Formula/inshirah.rb
   # url:    .../inshirah-<version>.tar.gz
   # sha256: the value below
   curl -sL https://pypi.org/pypi/inshirah/json \
     | jq -r '.urls[] | select(.packagetype=="sdist") | .digests.sha256'
   ```

3. Let Homebrew write the dependency pins — they are derived from PyPI, so
   hand-writing them is how a formula ends up installing something the tests
   never saw:

   ```sh
   brew update-python-resources Formula/inshirah.rb
   ```

4. Check it actually installs, from a clean prefix:

   ```sh
   brew install --build-from-source Formula/inshirah.rb
   brew test inshirah
   brew audit --strict --online inshirah
   ```

5. Commit and push. `brew install umairkhancis/tap/inshirah` is live as soon as
   the push lands — there is no review queue for a personal tap.

## A note on size

`claude-agent-sdk` ships a bundled Claude Code binary of a couple of hundred
megabytes. The formula is honest about this in its comments; `brew install` will
take a while and there is nothing to be done about it short of dropping the
bundle, which would trade a slow install for a broken first run.

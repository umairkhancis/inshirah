# Distribution

Inshirah runs on the user's machine, against the Claude Code they are already
signed in to. There is nothing here to deploy to a server, and that is the
point: no backend means nothing of theirs to leak, and it is the only version of
the trust claim that survives contact with someone reading the source.

So "deploy" means "publish", in two places:

- **PyPI** — `uvx inshirah`, `uv tool install inshirah`, `pipx install inshirah`.
  Automated: push a `v*` tag and `.github/workflows/release.yml` builds and
  uploads it.
- **Homebrew** — `brew install umairkhancis/tap/inshirah`. Manual, and downstream
  of PyPI. See [homebrew.md](homebrew.md).

## Cutting a release

```sh
# 1. version, in the one place it lives
$EDITOR inshirah/__init__.py          # __version__ = "0.2.0"

# 2. prove it builds and installs somewhere clean
uv build
uv venv /tmp/fresh && uv pip install --python /tmp/fresh/bin/python dist/inshirah-*.whl
/tmp/fresh/bin/inshirah --version

# 3. tag, which is what triggers the upload
git tag v0.2.0 && git push --tags

# 4. Homebrew, once PyPI has the sdist
```

`release.yml` publishes with PyPI's trusted publishing (OIDC), so there is no
API token in the repository and no secret to rotate. It has to be enabled once,
at <https://pypi.org/manage/account/publishing/>: project `inshirah`, owner
`umairkhancis`, repo `inshirah`, workflow `release.yml`, environment `pypi`.

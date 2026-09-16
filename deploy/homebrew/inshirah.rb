# Homebrew formula for Inshirah.
#
# This file lives here so it is versioned next to the thing it installs, but
# Homebrew will not read it from this repository. It has to be copied into a tap
# — a repo named `homebrew-tap` on the same account — as `Formula/inshirah.rb`,
# which is what makes `brew install umairkhancis/tap/inshirah` resolve.
#
# See docs/homebrew.md for the release checklist. The short version:
# publish to PyPI first, then point `url` at the sdist PyPI serves, then let
# Homebrew write the resource blocks rather than writing them by hand.
class Inshirah < Formula
  include Language::Python::Virtualenv

  desc "Thoughtful surface over Claude Code: edit any message, branch any thread"
  homepage "https://github.com/umairkhancis/inshirah"
  url "https://files.pythonhosted.org/packages/source/i/inshirah/inshirah-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_THE_SDIST_SHA256"
  license "MIT"

  depends_on "python@3.13"

  # Generated, never hand-written:
  #
  #     brew update-python-resources Formula/inshirah.rb
  #
  # It reads the dependency tree off PyPI and writes a `resource` block per
  # package, so this section only exists once a release is actually published.
  # Note that claude-agent-sdk carries a bundled Claude Code binary, so expect
  # the install to be a few hundred megabytes.

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "inshirah #{version}", shell_output("#{bin}/inshirah --version")
    # Runs entirely locally and starts no session, so it is safe in a sandbox
    # with no network and no Claude Code login.
    assert_match "no telemetry", shell_output("#{bin}/inshirah --privacy")
  end
end

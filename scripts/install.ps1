# Inshirah installer - Windows.
#
#   powershell -c "irm https://raw.githubusercontent.com/umairkhancis/inshirah/main/scripts/install.ps1 | iex"
#
# The same three steps as install.sh: install uv if missing, install Inshirah
# with it, say what to do next. No admin rights, nothing outside your profile,
# no data sent anywhere.
#
# Windows is the least-tested platform here. The app is Textual and the Agent
# SDK, both of which support it, but nobody has run this end to end on Windows
# yet - if something is broken, that is where it will be.
$ErrorActionPreference = 'Stop'

function Say($m) { Write-Host $m }

if (Get-Command uv -ErrorAction SilentlyContinue) {
    Say 'uv: already installed'
} else {
    Say 'uv: installing (Inshirah is a Python tool; uv is what puts it on PATH)'
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
}

# The running shell predates the install, so put uv where this script can see it.
$uvBin = Join-Path $env:USERPROFILE '.local\bin'
$env:Path = "$uvBin;$env:Path"

Say 'inshirah: installing'
uv tool install --upgrade inshirah | Out-Null
uv tool update-shell 2>$null | Out-Null

$version = (inshirah --version) 2>$null
if (-not $version) { throw 'installed, but the command does not run' }

Say ''
Say "Installed: $version"
Say ''
Say 'Next:'
Say '  inshirah --login     # once, only if you have never signed in to Claude Code'
Say '  inshirah             # from any project directory'
Say ''
Say 'It runs on this machine, against your own Claude Code. Nothing is sent'
Say 'anywhere else - run "inshirah --privacy" to see exactly what that means.'

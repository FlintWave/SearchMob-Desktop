# SearchMob Desktop

[![CI](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

**Private, on-device metasearch for Windows, macOS, and Linux.** A Python port of
[SearchMob for Android](https://github.com/FlintWave/SearchMob) with the same engines, the same
privacy proxy, and the same store-nothing-by-default behavior.

> **Status:** released. Metasearch, the local HTTP server, encrypted storage, the suggestions
> endpoint, on-device correction, result personalization, network mode, and the PySide6 GUI are all
> implemented and shipped in the installers. Track the roadmap in [`ROADMAP.md`](ROADMAP.md).

## What it does (parity with the Android app)

- **Metasearch** against DuckDuckGo, Mojeek, Marginalia, Mwmbl, and Wikipedia, plus optional
  bring-your-own Brave / Mojeek / Kagi API keys. Never scrapes Google. Results are de-duplicated and
  merged. BYO keys are read from the encrypted vault (saved in Settings) or, failing that, the
  `SEARCHMOB_BRAVE_API_KEY`, `SEARCHMOB_MOJEEK_API_KEY`, and `SEARCHMOB_KAGI_API_KEY` environment
  variables.
- **Privacy proxy**: no cookies, no referrer, no user/device identifier; the User-Agent is rotated
  per request.
- **On-device "did you mean"**: a fully offline spell / "similar sounding" corrector (phonetic +
  edit-distance over a bundled word list, optionally augmented by your own history) suggests a
  correction for misspelled queries. No query ever leaves the device for this.
- **Result personalization ("filter bubbles"), local and private**: block / lower / raise / pin
  results by domain (right-click a result), plus saved **scopes** (domain/keyword filters; the
  ready-to-use samples are installed by default and selectable before you even search) and imported
  Brave Goggles-format rules. Rules live in the encrypted vault and are applied on-device to both
  the in-app and browser results; nothing is sent upstream.
- **Search verticals**: category tabs for **Web**, **News**, **Forums**, and **Academic**. Each is a
  scoped search over the same engines (a `site:` filter, no new third-party API) with a sensible
  default sort. Available in the app and on the served page (`?vertical=`).
- **Result sorting**: Freshest + Relevant (default), Date, or Relevance — in the app and via `?sort=`.
- **Contextual Wikipedia summary** card above the results for entity-like queries (confidence-gated,
  fail-soft), in the app and on the served page.
- **AI-slop / low-quality filter**: a bundled, on-device domain blocklist that downranks (default) or
  hides results from AI content farms; off / downrank / hide in Settings. No query leaves the device.
- **Settings in the browser**: the served results page has its own owner-only (loopback) Settings
  page mirroring the app — default sort, the slop filter, the summary card, suggestions, full
  domain-rule and scope management, Goggles import, and history view/clear.
- **Optional local-AI answer box** (desktop only): when a local model server (Ollama / LM Studio) is
  running, a short cited answer summarizing your own results — off by default, loopback-only.
- **MCP server** (`searchmob-desktop mcp`): exposes the metasearch as a Model Context Protocol
  `web_search` tool over stdio, so a local AI agent (Claude Desktop, IDE assistants) can run its web
  searches through SearchMob's private metasearch instead of a third-party search API. Opt-in; the
  config snippet is in Settings → AI access.
- **Outbound traffic disclosure**: the only outbound traffic is the searches you run, plus an
  optional once-a-day update check to GitHub that you can turn off in settings.
- **Local HTTP server** so any browser can use SearchMob as its default search engine. Loopback-only
  by default; opt-in network mode (`0.0.0.0`) for Tailscale or LAN use, behind a warning gate and an
  access-token + DNS-rebind guard for off-device clients.
- **Search-suggestions endpoint** (OpenSearch `application/x-suggestions+json`) advertised in the
  descriptor, sourced from local history plus an opt-in upstream.
- **Store-nothing by default.** Opt-in encrypted history (SQLCipher + Argon2id); optional
  zero-knowledge passphrase.
- **Three surfaces**: a Qt-based GUI, a Typer CLI for headless and scripted use, and a background
  HTTP service.

## Install

Grab the current version from the [latest GitHub Release](https://github.com/FlintWave/SearchMob-Desktop/releases/latest) (the version history is in [`CHANGELOG.md`](CHANGELOG.md)). Two install paths:

### End users: native installer (recommended)

Grab the installer for your OS from the [latest GitHub Release](https://github.com/FlintWave/SearchMob-Desktop/releases):

- Windows: `searchmob-desktop-<version>.msi`
- macOS: `searchmob-desktop-<version>.dmg`
- Linux: `searchmob-desktop_<version>_amd64.deb` (Debian/Ubuntu), `searchmob_desktop-<version>.rpm`
  (Fedora/RHEL), or the `.flatpak` bundle. (The AppImage target was dropped — Briefcase's AppImage
  is unreliable for PySide.) You can also install via `pipx` (below).

> **Installers are unsigned.** The `.msi` and `.dmg` are ad-hoc signed and will trigger SmartScreen
> / Gatekeeper warnings; Authenticode signing (Windows) and Apple notarization (macOS) are planned
> once the signing secrets are wired into CI. Verify any download against the published
> `SHA256SUMS` (below) before installing.

### Verify your download

Every release ships a `SHA256SUMS` file listing the checksum of each installer (download it from
the same [release page](https://github.com/FlintWave/SearchMob-Desktop/releases) into the same
folder as your installer). The filenames in it match the release assets exactly. To check:

```bash
# Linux
sha256sum --ignore-missing -c SHA256SUMS

# macOS
shasum -a 256 -c SHA256SUMS   # add --ignore-missing on coreutils' gsha256sum
```

```powershell
# Windows (PowerShell): compare the printed hash to the matching line in SHA256SUMS
(Get-FileHash .\SearchMob.Desktop-<version>.msi -Algorithm SHA256).Hash
```

`--ignore-missing` checks only the file(s) you actually downloaded. An `OK` line means the download
is intact. (This guards against corruption and tampering in transit; it is not a substitute for the
code-signing that is still to come.)

### Developers / source install

```bash
pipx install git+https://github.com/FlintWave/SearchMob-Desktop@main
# or, with the GUI extra:
pipx install "searchmob-desktop[gui] @ git+https://github.com/FlintWave/SearchMob-Desktop@main"

searchmob-desktop --version
searchmob-desktop --help
```

## CLI

```bash
searchmob-desktop search "privacy tools"   # one-shot metasearch, prints a table
searchmob-desktop serve                    # run the local HTTP server (browser integration)
searchmob-desktop gui                      # launch the desktop GUI
searchmob-desktop mcp                      # run the MCP server (stdio) for a local AI agent
searchmob-desktop vault --help             # manage the encrypted-storage vault
searchmob-desktop --version
```

## Versioning

Same Ubuntu-style scheme as the Android app: `YY.MM.VV` (e.g. `26.05.00`). Releases are tagged
`vYY.MM.VV`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). We use [Conventional Commits](https://www.conventionalcommits.org)
and build each feature on its own branch with green CI before merging. Please also read
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) and, for security reports, [`SECURITY.md`](SECURITY.md).

## Credits

App icon: <a href="https://www.flaticon.com/free-icons/search" title="search icons">Search icons created by Freepik - Flaticon</a>.

The bundled correction dictionary derives from [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords)
(word frequencies, CC BY-SA 4.0, from the OpenSubtitles corpus) and public-domain name lists; see
[`src/searchmob_desktop/resources/dict/NOTICE`](src/searchmob_desktop/resources/dict/NOTICE).

## Trademarks

SearchMob is not affiliated with, endorsed by, or sponsored by DuckDuckGo, Mojeek, Marginalia,
Mwmbl, Wikipedia, Brave, Kagi, Google, or Tailscale. All product names, logos, and brands are the
property of their respective owners and are used here only to identify the services SearchMob
interoperates with. The "Goggles" rule format is Brave's; "Brave" and "Goggles" are trademarks of
Brave Software, Inc.

## License

[AGPL-3.0-or-later](LICENSE). If you run a modified version that users interact with over a network,
you must offer them the corresponding source.

Copyright © 2026 FlintWave. Contact: flintwave@tuta.com

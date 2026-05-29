# SearchMob Desktop

[![CI](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

**Private, on-device metasearch for Windows, macOS, and Linux.** A Python port of
[SearchMob for Android](https://github.com/FlintWave/SearchMob) with the same engines, the same
privacy proxy, and the same store-nothing-by-default behavior.

> **Status:** alpha, feature-complete. Metasearch, the local HTTP server, encrypted storage, the
> suggestions endpoint, on-device correction, result personalization, network mode, and the PySide6
> GUI are all implemented. Track the roadmap in [`ROADMAP.md`](ROADMAP.md).

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
  results by domain (right-click a result), plus saved **scopes** (domain/keyword filters, with
  ready-to-use samples) and imported Brave Goggles-format rules. Rules live in the encrypted vault
  and are applied on-device to both the in-app and browser results; nothing is sent upstream.
- **Outbound traffic disclosure**: the only outbound traffic is the searches you run, plus an
  optional once-a-day update check to GitHub that you can turn off in settings.
- **Local HTTP server** so any browser can use SearchMob as its default search engine. Loopback-only
  by default; opt-in network mode (`0.0.0.0`) for Tailscale or LAN use, with the same warning gate.
- **Search-suggestions endpoint** (OpenSearch `application/x-suggestions+json`) advertised in the
  descriptor, sourced from local history plus an opt-in upstream.
- **Store-nothing by default.** Opt-in encrypted history (SQLCipher + Argon2id); optional
  zero-knowledge passphrase.
- **Three surfaces**: a Qt-based GUI, a Typer CLI for headless and scripted use, and a background
  HTTP service.

## Install (alpha)

The latest release is `26.05.01` (see [`CHANGELOG.md`](CHANGELOG.md)). Two install paths:

### End users: native installer (recommended)

Grab the installer for your OS from the [latest GitHub Release](https://github.com/FlintWave/SearchMob-Desktop/releases):

- Windows: `searchmob-desktop-<version>.msi`
- macOS: `searchmob-desktop-<version>.dmg`
- Linux: install via `pipx` (below). A native Linux package (Flatpak or `.deb`/`.rpm`) is planned;
  the AppImage build proved unreliable for a PySide app and was dropped.

Every release also publishes a `SHA256SUMS` file you can verify before installing.

> **First release is unsigned.** The `.msi` and `.dmg` are built with `--adhoc-sign` and will
> trigger SmartScreen / Gatekeeper warnings. Authenticode signing on Windows and Apple notarization
> on macOS land in a follow-up release once the signing secrets are wired into CI; the SHA256SUMS
> file is the integrity anchor for the alpha.

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
searchmob-desktop search "privacy tools"   # one-shot metasearch (planned)
searchmob-desktop serve                    # local HTTP server (planned)
searchmob-desktop gui                      # launch the desktop GUI (planned)
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

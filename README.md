# SearchMob Desktop

[![CI](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/FlintWave/SearchMob-Desktop/actions/workflows/ci.yml)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](LICENSE)

**Private, on-device metasearch for Windows, macOS, and Linux.** A Python port of
[SearchMob for Android](https://github.com/FlintWave/SearchMob) with the same engines, the same
privacy proxy, and the same store-nothing-by-default behavior.

> **Status:** scaffold. The CLI is wired up but the metasearch, local HTTP server, encrypted storage,
> suggestions endpoint, and GUI are placeholders. Track progress in [`ROADMAP.md`](ROADMAP.md).

## What it will do (parity with the Android app)

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

The first published release is `26.05.00`. Two install paths:

### End users: native installer (recommended)

Grab the installer for your OS from the [latest GitHub Release](https://github.com/FlintWave/SearchMob-Desktop/releases):

- Windows: `searchmob-desktop-<version>.msi`
- macOS: `searchmob-desktop-<version>.dmg`
- Linux (any modern distro): `SearchMob_Desktop-<version>-x86_64.AppImage` (one portable binary, `chmod +x` and run)

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

## License

[AGPL-3.0-or-later](LICENSE). If you run a modified version that users interact with over a network,
you must offer them the corresponding source.

Copyright © 2026 FlintWave. Contact: flintwave@tuta.com

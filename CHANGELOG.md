# Changelog

All notable changes to SearchMob Desktop are documented here. The version scheme is Ubuntu-style
`YY.MM.VV` and releases are tagged `vYY.MM.VV`.

## 26.05.02 — 2026-05-29

### Added
- **Native Linux installers**: `.deb` (Debian/Ubuntu), `.rpm` (Fedora/RHEL), and a Flatpak bundle,
  built with Briefcase's `linux system`/`flatpak` backends. (The AppImage target, which never built
  reliably for a PySide app, is gone.)
- **Network-mode access token**: when the server is bound to a non-loopback address, requests from
  other devices must carry a per-install token (loopback is exempt). The token is minted when you
  enable network mode and baked into the browser-setup and OpenSearch URLs.

### Security
- **Host-header allowlist** on the local server (DNS-rebinding defense): only loopback, the bound
  host, and (under a wildcard bind) IP-literal hosts are accepted.
- Added a pinned `requirements.lock` constraints file for more reproducible builds.

## 26.05.01 — 2026-05-29

A large feature release bringing the desktop app to parity with the Android app, plus a security
and legal-compliance hardening pass.

### Added
- **Modern UI + tray.** A cleaner, COSMIC-leaning light/dark interface with card-style results and
  a friendly empty state; the window minimizes to the system tray instead of quitting.
- **Kagi API engine** (bring-your-own key). BYO keys (Brave / Mojeek / Kagi) are now resolved from
  the encrypted vault first, then the matching environment variable — keys saved in Settings
  actually take effect (previously env-var only).
- **Search history**: an in-app viewer with delete / clear, JSON export & import (interoperable
  with the Android app) for moving to a new device, and a 30-day TTL. When enabled and a vault is
  available, history persists encrypted on disk (SQLCipher); otherwise it is per-session.
- **On-device "did you mean"**: a fully offline spell / similar-sounding corrector (Double
  Metaphone + edit distance over a bundled word list, augmented by your own history). Surfaced as a
  banner in the app and on the served results page; no query leaves the device for this.
- **Result personalization ("filter bubbles")**: block / lower / raise / pin by domain (right-click
  a result), saved **scopes** (domain/keyword filters) with a set of ready-to-use samples, and
  imported Brave Goggles-format rules. Rules live in the encrypted vault and apply on-device to both
  the in-app and browser results.
- **Network mode (Phase 7)**: opt-in LAN/Tailscale binding behind a warning gate, with the privacy
  guard that local search-history suggestions are never served to other devices on the network.

### Changed
- README updated from "scaffold" to feature-complete alpha; user-facing "lenses" → "scopes".
- Double Metaphone is now vendored (BSD) instead of depending on the sdist-only `metaphone`
  package, so the macOS/Windows installers build from wheels cleanly.
- Release installers are Windows `.msi` and macOS `.dmg`; the Linux AppImage was dropped (Briefcase
  AppImage is unreliable for PySide). Linux users install via `pipx` for now.

### Security
- Engine responses are size-bounded (streamed, capped) so a hostile upstream can't exhaust memory;
  the HTTP client ignores proxy/SSLKEYLOG environment variables.
- The local server sends `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, and
  `X-Frame-Options: DENY`, and result links carry `rel="noopener noreferrer"` — clicking a result
  no longer leaks the query as a Referer.
- Imported goggle / ranking / history files are size-capped; the bundled dictionary is decompressed
  with a ceiling; `prefs.json`, the vault metadata, and the encrypted prefs blob are written `0600`.

### Legal / licensing
- The bundled dictionary NOTICE now correctly attributes the word-frequency data as CC BY-SA 4.0.
- Added a trademark / non-affiliation disclaimer (About + README) and a note that Brave's Search
  API terms prohibit caching results when history is enabled with a Brave key.

## 26.05.00 — 2026-05

- First desktop release: metasearch engine adapters + privacy proxy, the local HTTP server with the
  OpenSearch descriptor and suggestions endpoint, encrypted storage (AES-GCM + Argon2id + SQLCipher
  + OS keyring), settings / suggestions / GitHub update check, the PySide6 GUI, and Briefcase native
  installers (Windows `.msi`, macOS `.dmg`, Linux AppImage).

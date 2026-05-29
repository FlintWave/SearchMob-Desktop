# Changelog

All notable changes to SearchMob Desktop are documented here. The version scheme is Ubuntu-style
`YY.MM.VV` and releases are tagged `vYY.MM.VV`.

## Unreleased

### Added
- **Contextual Wikipedia summary box.** For entity-like queries, a short knowledge-panel card from
  the related Wikipedia article now appears above the results on the served page (the in-browser
  surface), with the title, description, lead extract, and a link. Fail-soft and confidence-gated
  (no box for questions, navigational input, disambiguation, or low-confidence matches); adds at
  most one extra request to Wikipedia through the privacy proxy. Toggle in Settings -> Suggestions.
- **First-run setup wizard.** On first launch the desktop app now walks you through a short,
  skippable guide (Welcome, privacy, making SearchMob your browser's search engine, and - where
  available - running it as a background service), mirroring the Android onboarding. It is OS-aware:
  the background-service step only appears on platforms that support one and names that platform's
  actual mechanism (systemd / launchd / scheduled task). Re-runnable any time from Settings ->
  Device setup -> "Run the setup guide again".

## 26.05.04 — 2026-05-29

### Added
- **Run SearchMob as a background service (Linux, macOS, Windows).** Settings -> Device setup ->
  "Run in the background" installs a per-user service that runs the local search server headless, so
  the browser can use SearchMob even when the app window is closed: a systemd user unit on Linux, a
  launchd LaunchAgent on macOS, and a logon Scheduled Task on Windows (no admin rights needed).
  Install / reinstall / stop-and-remove from the UI; the service binds the same address as the
  in-app server (loopback, or the network address when network mode is on). The app still opens the
  GUI on a normal launch; this is opt-in.
- **Personalization controls in the browser (served UI).** The results page the browser sees now
  has the same scope/ranking tools as the app: per-result **Block / Lower / Raise / Pin** by domain
  and a **scope (lens) selector**. Edits persist to the encrypted vault and apply on the next search
  (the server reads rules live, no restart). The editing routes are **loopback-only** - a device
  reaching the server over the network can search but cannot change the owner's rules - and are
  same-origin guarded against CSRF.
- **Use a hostname instead of an IP for browser setup.** The setup URLs now show `localhost` for
  the normal loopback case. In network mode you can add trusted hostnames (Settings -> Network),
  e.g. a Tailscale MagicDNS or mDNS `<host>.local` name, and the server accepts them in the
  Host-header allowlist; the machine's own hostname is accepted automatically. Reaching the server
  by IP still works. The browser-setup launcher also now includes the network access token when
  opened from the main window (previously only the Settings entry did).

### Changed
- **Copying a URL in the browser-setup wizard no longer pops a modal.** Instead the field flashes
  a green outline with a checkmark that fades out over it, so the confirmation does not interrupt.

### Fixed
- **Fixed a crash when using "Check for updates" (and other background actions).** Background
  workers (the update check, in-app searches) are `QRunnable`s whose signal carrier was only held by
  a local variable; once the handler returned, Python could garbage-collect the worker while its
  pool thread was still running, so the cross-thread result delivery hit freed memory and the app
  vanished - most reliably when the button was clicked rapidly. Workers are now retained until their
  result is delivered, and the "Check now" button is disabled while a check is in flight.
- **Result links are now stripped of tracking parameters before you click them.** The tracker
  list (`utm_*`, `fbclid`, `gclid`, `mc_cid`, `igshid`, `ref`, ...) was only applied to the dedup
  key; the displayed link kept the raw upstream URL. The aggregator now surfaces a cleaned URL, so
  in-app, CLI, and served-page links all drop trackers (functional query params are preserved).
- **Browser-setup wizard now uses the `%s` search-term placeholder** that Firefox-family and
  Chromium "add a search engine" dialogs expect. Pasting the old `{searchTerms}` form into
  LibreWolf/Firefox failed with "Try including %s in place of the search term". The `{searchTerms}`
  form is still served in the OpenSearch descriptor for the easier auto-detect path, which the
  wizard now recommends first.

## 26.05.03 — 2026-05-29

### Fixed
- **Desktop app now opens the GUI when launched from the app menu / installer.** The packaged app
  runs `python -m searchmob_desktop`, whose entry point previously invoked the CLI and exited with
  the help text, so a desktop launch showed no window. The package entry point now opens the GUI
  when run with no arguments (and still defers to the CLI when given subcommands, so
  `python -m searchmob_desktop search ...` keeps working). The `searchmob-desktop` console script
  is unchanged.

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

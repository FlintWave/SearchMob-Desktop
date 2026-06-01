# Changelog

All notable changes to SearchMob Desktop are documented here. The version scheme is Ubuntu-style
`YY.MM.VV` and releases are tagged `vYY.MM.VV`.

## 26.05.12 — 2026-05-31

### Changed
- **Settings dialog redesign.** The sections moved from a row of top tabs to a left-hand navigation
  column, and the API keys are now entered inline on the **Search engines** page: each key-requiring
  engine has its key field directly under its checkbox, grayed out until you check that engine. The
  standalone "API keys" section is gone.
- **Key-requiring engines are now unchecked by default.** The free engines stay on out of the box;
  Brave / Mojeek API / Kagi start off and are turned on when you add their key (they could never run
  without one anyway). Free engines are unaffected.

### Fixed
- Saving or clearing a **Kagi** key updated the right engine's status (previously it could update
  Mojeek's), now that each engine owns its inline field.

## 26.05.11 — 2026-05-31

### Changed
- **The MCP `web_search` tool now runs in a dedicated, hardened "agent" scope.** Results handed to a
  local AI agent always apply the AI-slop blocklist in *hide* mode (not just downrank), honor an
  optional user-curated `agent_safety_excludes` domain list, and have their titles/snippets stripped
  of control characters and length-capped, with non-`http(s)` links dropped. The agent scope is kept
  in the non-secret prefs (not the encrypted vault), so it still applies when a zero-knowledge
  passphrase keeps the headless MCP subprocess out of the vault. The user's search history is never
  read or recorded by the tool, and its description now states accurately that vault-backed
  personalization applies only when the vault is unlocked.

## 26.05.10 — 2026-05-31

### Added
- **MCP server** (`searchmob-desktop mcp`). Exposes the metasearch as a Model Context Protocol
  `web_search` tool over stdio so a local AI agent (Claude Desktop, IDE assistants) can run its web
  searches through SearchMob's private metasearch instead of a third-party search API. Opt-in and
  loopback/stdio only; the ready-to-paste client config is in Settings -> AI access.
- **Sample scopes are installed by default** (no "add them" step), and the scope selector is shown in
  the app and on the served home page before you run a search.
- **Link to the Android app** from the About dialog.

### Changed
- The URL tracker-stripping list now matches the Android app exactly (adds `gclsrc`, `msclkid`).

### Fixed
- **Accessibility of the served pages and the GUI.** Served pages declare `<html lang>`; search
  inputs and the Sort/Scope selects have accessible names / associated labels; the vertical bar is a
  labeled `nav` with `aria-current` on the active tab (no longer color-only) and a contrast-corrected
  active chip; a visible keyboard focus ring and `prefers-reduced-motion` support were added. The
  BYO API-key, trusted-hostname, and passphrase fields in Settings now have accessible names.
- The MCP `web_search` tool clamps the query length, matching the HTTP server.

## 26.05.09 — 2026-05-30

### Added
- **Settings in the browser.** The served results UI (the surface most searches happen on) now has
  its own Settings page, reachable from a link in the top bar and served even when only the
  background service is running. It mirrors the desktop Settings where it is safe to do so over the
  local connection: default sort, the AI-slop / low-quality filter mode, the Wikipedia summary card,
  and upstream autocomplete; full management of your per-domain rules; create / edit / delete and
  select **scopes** (lenses); **Goggles** import (paste or pick a file) and clear; and a view of your
  recent search history with a clear button. Every change is owner-only (only this computer can open
  or change it) and takes effect on the next search without restarting the server.

### Fixed
- **Results now open on a single click** in the app. The in-app results list previously needed a
  double-click, so a single click looked like nothing happened; it now opens on one click, matching
  the browser page (the right-click ranking menu and keyboard Enter are unchanged).
- **The background service actually runs now (and starts at boot).** The installed service never
  started: its command was built for a plain Python interpreter, but the packaged app is its own
  executable, so it exited immediately and the system retried it forever. The command is now correct
  for the packaged app, and installing the service also enables systemd "lingering" so it starts
  with the system rather than only after you log in. This is what makes searching work with the app
  window closed.
- **The app and the background service no longer fight over the port.** When the service is already
  running, opening the app now detects and reuses it instead of trying to start a second server on
  the same port (which failed). The window shows it is using the background service, and closing the
  window leaves search running.

## 26.05.08 — 2026-05-29

### Added
- **Light/dark toggle on the main window**, next to the search box (a sun/moon button), mirroring
  the served page. It flips and persists the theme without opening Settings.

### Changed
- **The local AI answer now streams.** The answer appears token by token as the model produces it,
  instead of waiting (and looking stalled) until the whole answer is finished. This matters for
  larger local models that take a while to begin replying; you now see it fill in live, and a
  slow-but-progressing generation is never cut off by a timeout.

### Fixed
- **The local server now starts on launch**, so SearchMob is reachable (and usable as your browser's
  search engine) the moment the app opens, without starting it by hand.
- **Local AI was easy to leave inert.** The Local AI settings tab is now a single Model dropdown
  ("Off" plus every model found on this machine): picking a model turns the answer box on, so a
  chosen model is never silently disabled. Models are detected automatically when you open the tab.
- **Result scope (lens) selector** is now available on the main window next to the Sort control, not
  just on the served page; it appears once you have at least one saved lens.
- **Zero-knowledge passphrase setup** no longer fails with "the vault is not unlocked" when the OS
  keyring's availability changed since the vault was created. Unlock now tries every key-encryption
  key the vault could have been wrapped with (OS keyring and the on-disk fallback).
- **The first-run wizard opens centered over the main window** instead of in a screen corner.

### Added
- **Result sorting (freshest by date + relevance).** A new Sort control (in the app and on the
  served page) offers **Freshest + Relevant** (default), **Date** (newest first), and **Relevance**.
  Dates are extracted best-effort from each result's snippet/title ("3 days ago", "May 28, 2026",
  ISO, ...) with guards against future-date junk and bare years; the default blend gives recent
  results a boost while keeping undated results at full relevance standing (so evergreen searches
  look unchanged), and leans harder into freshness for obviously time-sensitive queries (release
  date, latest, score, a current/next year). The choice persists in the app and is a `?sort=` URL
  param on the served page.
- **AI-slop / low-quality content filter.** Results from a bundled, CC0-licensed list of
  AI-content-farm and low-quality domains can be downranked or hidden, entirely on-device (no query
  leaves the machine for filtering). Three modes in Settings -> Result ranking: **Downrank**
  (default, on), **Hide**, and **Off**. The filter runs after your own per-domain rules and goggles,
  so an explicit rule always wins and you can rescue a false positive by setting that domain to
  Normal or Raise.
- **Search verticals (category tabs).** A row of categories above the results: **Web** (default),
  **News**, **Forums**, and **Academic**. Each is a scoped search over the same engines (a `site:`
  filter the engines understand) plus a sensible default sort, so no new service ever sees your
  query and no API key is involved. News favors recent major outlets; Forums covers discussion
  sites; Academic covers scholarly sources. Available in the app and on the served page (`?vertical=`).
- **Optional local-AI answer box.** When you have a language-model server running on this computer
  (**Ollama** on port 11434 or **LM Studio** on port 1234), the app can show a short, cited answer
  above the results, summarizing your own results. It is off by default, only appears once you enable
  it and detect a local model in Settings -> Local AI, and **never touches the network** - it talks
  only to the loopback model server and nowhere else.

## 26.05.05 — 2026-05-29

### Added
- **Contextual Wikipedia summary box.** For entity-like queries, a short knowledge-panel card from
  the related Wikipedia article now appears above the results, both **in the app** and on the
  **served page**, with the title, description, lead extract, and a link. Fail-soft and
  confidence-gated (no box for questions, navigational input, disambiguation, or low-confidence
  matches); adds at most one extra request to Wikipedia through the privacy proxy. Toggle in
  Settings -> Suggestions.
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

# SearchMob Desktop roadmap

The desktop port targets parity with the Android app. Phase ordering mirrors the Android phases so
shared design decisions land in the same order.

## Phase 0 — scaffold (this commit)

- Project layout (`src/searchmob_desktop/`), `pyproject.toml`, license, security policy, conduct,
  contributing guide, CI (lint + tests), Dependabot.
- Typer CLI shell with placeholder `search`, `serve`, `gui` subcommands; `--version` works.
- Smoke tests in `tests/`.

## Phase 1 — metasearch engine adapters and privacy proxy

- Port the engine adapter pattern from the Android app: a shared async `httpx` client with cookies
  off, `Referer` and forwarding headers stripped, and a rotated User-Agent.
- One adapter per engine (DuckDuckGo, Mojeek, Marginalia, Mwmbl, Wikipedia) plus the BYO key
  variants for Brave and Mojeek.
- Aggregator with reciprocal-rank fusion, normalized-URL dedup, bounded concurrency, timeouts, and
  fail-soft per-engine errors.

## Phase 2 — local HTTP server (Starlette + Uvicorn)

- `/`, `/search`, `/api/search`, `/healthz`, `/opensearch.xml`, `/suggest` parity with the Android
  server. Loopback-only by default.
- HTML-escaped result rendering with a URL scheme allowlist for `href`; query length cap; bounded
  upstream body reads. `/suggest` returns OpenSearch suggestions JSON with the correct content type.

## Phase 3 — encrypted storage

- `cryptography` AES-GCM for the prefs blob; `argon2-cffi` for the passphrase KDF; SQLCipher for the
  history database. Store-nothing default; opt-in history; optional zero-knowledge passphrase.

## Phase 4 — settings, suggestions, update check

- Persistent settings (theme, engines, BYO keys, network mode, suggestions toggle, update toggle).
- Local history suggestions plus opt-in upstream (DuckDuckGo ac) through the privacy proxy.
- Launch-time GitHub update check, on by default, throttled daily, disclosed in the About text.

## Phase 5 — GUI (PySide6)

- Main window with a search bar, results list, settings dialog, About + privacy view, and a
  background indicator for the local HTTP server.

## Phase 6 — Native installers (Briefcase)

- `briefcase package` builds `.msi`, `.dmg`, and `.deb` from the same project. Signing where
  feasible (Windows code-signing cert, Apple notarization). CLI-only install via `pipx` continues to
  work in parallel.

## Phase 7 — Network mode (done)

- The same Tailscale/LAN opt-in toggle and warning gate as the Android app. Server rebinds when the
  preference changes, and binds per the saved preference at launch.
- Privacy guard: when the server binds a non-loopback address (network mode), the `/suggest`
  endpoint stops serving the owner's local search history to other devices on the network.

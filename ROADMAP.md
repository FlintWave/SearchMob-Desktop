# SearchMob Desktop roadmap

The desktop port reached parity with the Android app and is shipped (see
[`CHANGELOG.md`](CHANGELOG.md)). This file records the build phases (all complete) and the remaining
future work.

## Shipped

All of the original parity phases are done and released:

- **Phase 0 — scaffold.** Project layout, `pyproject.toml`, CI (lint + tests), Dependabot, Typer CLI.
- **Phase 1 — engine adapters + privacy proxy.** Shared async `httpx` client (cookies off, `Referer`
  / forwarding headers stripped, rotated User-Agent, bounded response reads); adapters for
  DuckDuckGo, Mojeek, Marginalia, Mwmbl, Wikipedia, plus BYO-key Brave / Mojeek / Kagi; RRF
  aggregator with normalized-URL dedup, bounded concurrency, and fail-soft per-engine errors.
- **Phase 2 — local HTTP server (Starlette + Uvicorn).** `/`, `/search`, `/api/search`, `/healthz`,
  `/opensearch.xml`, `/suggest`; HTML escaping + URL scheme allowlist; query-length cap; security
  headers; loopback-only by default.
- **Phase 3 — encrypted storage.** AES-GCM prefs, Argon2id passphrase KDF, SQLCipher history;
  store-nothing default, opt-in history, optional zero-knowledge passphrase, OS keyring.
- **Phase 4 — settings, suggestions, update check.** Persistent settings; local + opt-in upstream
  suggestions; throttled, opt-out GitHub update check.
- **Phase 5 — GUI (PySide6).** Modern light/dark window, settings dialog, About/privacy view,
  history viewer, server controls, minimize-to-tray.
- **Phase 6 — native installers (Briefcase).** Windows `.msi`, macOS `.dmg`, and Linux `.deb` /
  `.rpm` / Flatpak, published to GitHub Releases with `SHA256SUMS`.
- **Phase 7 — network mode.** Opt-in LAN/Tailscale binding with a warning gate; the `/suggest`
  endpoint never serves local history to network clients; non-loopback access requires a token.

Beyond the original phases, parity work also shipped: the Kagi API engine, in-app history view with
JSON export/import and a 30-day TTL, on-device "did you mean" correction, result personalization
(domain rules, scopes with samples, Brave Goggles), a security-hardening pass (bounded responses,
security headers, Host-header allowlist, input caps, owner-only file permissions), and the
trademark / licensing fixes.

## Future

- **Code signing + notarization.** Authenticode (Windows) and Apple notarization (macOS) once the
  signing secrets are wired into CI; today's installers are ad-hoc / unsigned.
- **Flatpak stability + Flathub.** The Flatpak build is currently best-effort in CI; harden it and
  consider publishing to Flathub.
- **Network-mode rate limiting** on top of the existing access token.
- **Lens/scope creation wizard** and richer Goggles management in the GUI.

# Security Policy

SearchMob Desktop handles people's search activity, so we take security and privacy seriously.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting:
**Security → Report a vulnerability** (Private Vulnerability Reporting) on this repository.

Please include: a description, steps to reproduce, affected version/commit, and impact. We aim to
acknowledge reports within 7 days and to coordinate a fix and disclosure timeline with you.

If you cannot use GitHub's private reporting, contact the maintainer at **flintwave@tuta.com**. Email
is not encrypted in transit by default, so use it only to request a secure channel, not to send the
vulnerability details themselves.

## Scope

In scope: the SearchMob Desktop app, its local HTTP server, the encrypted storage layer, the
metasearch privacy proxy, the update-check path, and the build/release pipeline. Of particular
interest:

- Anything that leaks user queries or identity to upstream engines or third parties.
- Bypasses of the loopback-only binding (the local server must never be reachable off-device unless
  the user has explicitly enabled network mode, and even then only as configured).
- Weaknesses in encryption-at-rest or the optional zero-knowledge passphrase mode.
- Supply-chain issues in Python dependencies, the build, or CI.

## Good to know

- The app contains no telemetry and collects no analytics or device identifiers.
- The only outbound traffic is the searches you run, plus an optional once-a-day update check to
  GitHub that you can turn off in settings.
- Releases are signed where the platform supports it (Windows code-signing certificate, Apple
  notarization). Verify checksums on downloaded artifacts.
- Third-party GitHub Actions are pinned by commit SHA.

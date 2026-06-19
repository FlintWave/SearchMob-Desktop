#!/usr/bin/env python3
"""Build the bundled AI-slop / low-quality domain blocklist asset.

Downloads two actively-maintained, CC0-1.0 (public-domain) community lists, parses each into bare
registrable domains (dropping path-scoped, regex, comment, and header lines so a stray entry can
never block a whole legit domain), dedupes + sorts, and writes a gzipped one-domain-per-line asset
plus a NOTICE. Mirrors `tools/build-dictionary.*` for the correction dictionary: the generated
asset is committed for reproducibility, and this script documents exactly how it was produced.

Run from the repo root:  python tools/build_slop_list.py
"""

from __future__ import annotations

import gzip
import re
import urllib.request
from pathlib import Path

# (name, raw URL, format). Both are CC0-1.0 -> safe to bundle/redistribute in an AGPL app.
_SOURCES = [
    (
        "laylavish/uBlockOrigin-HUGE-AI-Blocklist",
        "https://raw.githubusercontent.com/laylavish/uBlockOrigin-HUGE-AI-Blocklist/main/noai_hosts.txt",
        "hosts",
    ),
    (
        "agsimmons/ai-content-blocklist",
        "https://raw.githubusercontent.com/agsimmons/ai-content-blocklist/refs/heads/main/uBlacklist.txt",
        "ublacklist",
    ),
]

_OUT_DIR = (
    Path(__file__).resolve().parent.parent / "src" / "searchmob_desktop" / "resources" / "blocklist"
)
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}$")


def _parse_hosts(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        # "0.0.0.0 domain.tld" / "127.0.0.1 domain.tld"; a bare domain line is also accepted.
        domain = parts[1] if len(parts) >= 2 else parts[0]
        out.add(domain.lower().removeprefix("www."))
    return out


def _parse_ublacklist(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        # Only match-pattern lines have "://"; comments (#/!), allowlist (@), regex (/.../), and
        # YAML-ish header (key: value) lines do not, so they are skipped here.
        if not line or line.startswith(("#", "!", "@")) or "://" not in line:
            continue
        # "*://*.domain.tld/*" -> take the host between "://" and the first path "/".
        host = line.split("://", 1)[1].removeprefix("*.").removeprefix("www.").split("/", 1)[0]
        if "*" in host or not host:
            continue
        out.add(host.lower())
    return out


def _load_allowlist() -> set[str]:
    """Read the curated allowlist (bare domains; `#` comments) the blocklist must never contain."""
    path = _OUT_DIR / "allowlist.txt"
    if not path.exists():
        return set()
    return {
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def main() -> None:
    domains: set[str] = set()
    for name, url, fmt in _SOURCES:
        print(f"fetching {name} ...")
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("utf-8", "replace")
        parsed = _parse_hosts(text) if fmt == "hosts" else _parse_ublacklist(text)
        # Keep only things that look like real domains.
        parsed = {d for d in parsed if _DOMAIN_RE.match(d)}
        print(f"  {len(parsed)} domains")
        domains |= parsed

    # Subtract the curated allowlist (and any subdomains of it): the community lists include the
    # official sites of AI companies and major dev hubs, which a search ranker must never bury. The
    # runtime loader applies the same subtraction; this just keeps the committed asset consistent.
    allow = _load_allowlist()
    domains = {d for d in domains if not any(d == a or d.endswith("." + a) for a in allow)}
    print(f"  {len(allow)} allowlisted domains subtracted")

    ordered = sorted(domains)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    asset = _OUT_DIR / "ai-slop-domains.txt.gz"
    with gzip.open(asset, "wt", encoding="utf-8") as f:
        f.write("\n".join(ordered) + "\n")
    print(f"wrote {len(ordered)} domains -> {asset}")

    notice = _OUT_DIR / "NOTICE"
    sources_md = "\n".join(
        f"- {name}\n  {url}\n  License: CC0-1.0 (public domain)" for name, url, _ in _SOURCES
    )
    notice.write_text(
        "AI-slop / low-quality domain blocklist (ai-slop-domains.txt.gz)\n"
        "==============================================================\n\n"
        "A merged snapshot of community-maintained AI-content-farm / low-quality domain lists,\n"
        "parsed to bare domains. Applied entirely on-device to downrank or hide listed domains;\n"
        "no query leaves the device for filtering.\n\n"
        "Sources (both CC0-1.0, public domain -> compatible with AGPL-3.0 redistribution):\n\n"
        f"{sources_md}\n\n"
        "Regenerate with:  python tools/build_slop_list.py\n",
        encoding="utf-8",
    )
    print(f"wrote {notice}")


if __name__ == "__main__":
    main()

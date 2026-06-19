"""Load the bundled AI-slop / low-quality domain blocklist.

The asset (`resources/blocklist/ai-slop-domains.txt.gz`, one bare domain per line) is a merged
snapshot of CC0-licensed community lists, built by `tools/build_slop_list.py`. It is applied
entirely on-device in the ranking pass to downrank or hide listed domains; no query ever leaves the
device for filtering. Loaded once and cached; any error yields an empty set so the filter simply
does nothing rather than failing a search.

The community lists are "hide AI from my browser" lists, so they include the official sites of AI
companies and major developer hubs (github.com, huggingface.co, openai.com, ...). A search ranker
must not bury those: a search for "huggingface" wants huggingface.co at the top. `allowlist.txt`
names the widely-known legitimate destinations to keep, and they are subtracted from the effective
blocklist here so the filter can only ever sink genuine low-quality domains.
"""

from __future__ import annotations

import gzip
from importlib.resources import files

_RESOURCE_PACKAGE = "searchmob_desktop.resources.blocklist"
_RESOURCE_NAME = "ai-slop-domains.txt.gz"
_ALLOWLIST_NAME = "allowlist.txt"
# Bound the decompressed size so a tampered/swapped asset cannot gzip-bomb the loader.
_MAX_BYTES = 8 * 1024 * 1024

_cache: frozenset[str] | None = None
_allow_cache: frozenset[str] | None = None


def load_slop_allowlist() -> frozenset[str]:
    """Domains that must never be treated as slop (cached). Empty set on any failure."""
    global _allow_cache
    if _allow_cache is not None:
        return _allow_cache
    try:
        resource = files(_RESOURCE_PACKAGE).joinpath(_ALLOWLIST_NAME)
        text = resource.read_text(encoding="utf-8")
        _allow_cache = frozenset(
            line.strip().lower()
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError, ValueError):
        _allow_cache = frozenset()
    return _allow_cache


def load_slop_domains() -> frozenset[str]:
    """Return the effective blocklist (asset minus allowlist), cached. Empty set on any failure."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        resource = files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME)
        with resource.open("rb") as raw, gzip.GzipFile(fileobj=raw) as gz:
            data = gz.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            _cache = frozenset()
            return _cache
        domains = {
            line.strip().lower()
            for line in data.decode("utf-8", "replace").splitlines()
            if line.strip() and not line.startswith("#")
        }
        # Drop every allowlisted domain AND any subdomain of one, so an explicit `discuss.x.com`
        # entry cannot survive when `x.com` is allowlisted.
        allow = load_slop_allowlist()
        _cache = frozenset(
            d for d in domains if not any(d == a or d.endswith("." + a) for a in allow)
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError, ValueError):
        _cache = frozenset()
    return _cache


def matches_blocklist(host: str, domains: frozenset[str]) -> bool:
    """True when `host` or a parent domain of it is in `domains` (suffix match at label edges)."""
    if not domains:
        return False
    parts = host.split(".")
    # Check the host and each parent (a.b.com, b.com) but never a bare TLD on its own.
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in domains:
            return True
    return False

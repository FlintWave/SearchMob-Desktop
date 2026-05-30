"""Load the bundled AI-slop / low-quality domain blocklist.

The asset (`resources/blocklist/ai-slop-domains.txt.gz`, one bare domain per line) is a merged
snapshot of CC0-licensed community lists, built by `tools/build_slop_list.py`. It is applied
entirely on-device in the ranking pass to downrank or hide listed domains; no query ever leaves the
device for filtering. Loaded once and cached; any error yields an empty set so the filter simply
does nothing rather than failing a search.
"""

from __future__ import annotations

import gzip
from importlib.resources import files

_RESOURCE_PACKAGE = "searchmob_desktop.resources.blocklist"
_RESOURCE_NAME = "ai-slop-domains.txt.gz"
# Bound the decompressed size so a tampered/swapped asset cannot gzip-bomb the loader.
_MAX_BYTES = 8 * 1024 * 1024

_cache: frozenset[str] | None = None


def load_slop_domains() -> frozenset[str]:
    """Return the blocklist domains as a frozenset (cached). Empty set on any failure."""
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
        _cache = frozenset(domains)
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

"""URL normalization for dedup.

Used as the dedup key by the aggregator: if two engines return the same page through slightly
different URLs (one with `?utm_source=...`, one without; or `HTTPS://Example.com/` vs
`https://example.com`), we want them to collapse into a single ranked row.

Rules (mirroring the spirit of the Android `UrlNormalizer.kt`):

* Drop common tracking query params (`utm_*`, `fbclid`, `gclid`, `gclsrc`, `msclkid`, `mc_cid`,
  `mc_eid`, `_hsenc`, `_hsmi`, `igshid`, `ref`, `ref_src`, `yclid`, `dclid`). This set is kept in
  sync with the Android app's `UrlNormalizer` so both strip the same trackers.
* Lowercase scheme and host.
* Strip a single trailing slash off the path, but leave the root path `/` alone.

We do not lowercase the path or sort query params here; the Android version sorts but we keep this
conservative since the desktop port has not yet shipped and changing the dedup key later is fine.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS: Final[frozenset[str]] = frozenset(
    {
        "fbclid",
        "gclid",
        "gclsrc",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "igshid",
        "ref",
        "ref_src",
        "yclid",
        "dclid",
    }
)
_TRACKING_PREFIXES: Final[tuple[str, ...]] = ("utm_",)


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    if lowered in _TRACKING_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _TRACKING_PREFIXES)


def strip_tracking_params(raw: str) -> str:
    """Return `raw` with known tracking query params removed, preserving the rest for display.

    Unlike `normalize_url` (which produces a lossy dedup key: lowercased host, trimmed trailing
    slash), this keeps the URL otherwise intact - scheme/host case, path, trailing slash, and
    fragment - so it is safe to show and click. It is applied to the URL the aggregator surfaces so
    the link a user follows does not carry `utm_*`/`fbclid`/etc.
    """
    trimmed = raw.strip()
    try:
        parts = urlsplit(trimmed)
    except ValueError:
        return trimmed
    if not parts.query:
        return trimmed
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
    ]
    query = urlencode(kept, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def normalize_url(raw: str) -> str:
    """Return the dedup-key form of `raw`. Falls back to the stripped input on parse failure."""
    trimmed = raw.strip()
    try:
        parts = urlsplit(trimmed)
    except ValueError:
        return trimmed

    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    path = parts.path
    if path != "/" and path.endswith("/"):
        path = path[:-1]

    if parts.query:
        kept = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
        ]
        query = urlencode(kept, doseq=True)
    else:
        query = ""

    return urlunsplit((scheme, host, path, query, parts.fragment))

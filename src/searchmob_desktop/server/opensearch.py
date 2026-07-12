"""OpenSearch descriptor builder.

Returns the XML body browsers (Chrome, Firefox, derivatives) read to offer SearchMob as a
search engine. Mirrors the descriptor produced by the Android Ktor server (`SearchServer.kt`):
the same `ShortName`, `Description`, `InputEncoding`, and the two `<Url>` entries (HTML results
and OpenSearch Suggestions) pointing at the origin the caller resolved (the request's own Host
for a network-mode visitor, the loopback origin otherwise).

The origin is interpolated into URL `template` attributes; the literal `{searchTerms}` token is
the OpenSearch placeholder the browser fills in at query time, so it is emitted verbatim. The
network-mode access token is deliberately never embedded: the descriptor is unauthenticated, so
a token in it would hand access to anyone on the network who can fetch this file. A network-mode
browser presents the token via `?token=` / `Authorization: Bearer` / `X-SearchMob-Token` instead.
"""

from __future__ import annotations

from html import escape


def build_descriptor(origin: str) -> bytes:
    """Return the OpenSearch 1.1 XML descriptor body for a server reachable at `origin`.

    `origin` is a scheme+authority like `http://127.0.0.1:8787` (no trailing slash), escaped for
    XML safety in case a future caller passes something exotic; the literal `{searchTerms}`
    placeholder is preserved (it is part of the OpenSearch template grammar, not a value the
    browser-controlled query can reach).
    """
    safe_origin = escape(origin.rstrip("/"), quote=True)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        "  <ShortName>SearchMob</ShortName>\n"
        "  <Description>Private on-device metasearch</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        f'  <Url type="text/html" template="{safe_origin}/search?q={{searchTerms}}"/>\n'
        f'  <Url type="application/x-suggestions+json"'
        f' template="{safe_origin}/suggest?q={{searchTerms}}"/>\n'
        "</OpenSearchDescription>\n"
    )
    return xml.encode("utf-8")

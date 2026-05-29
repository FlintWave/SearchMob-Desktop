"""OpenSearch descriptor builder.

Returns the XML body browsers (Chrome, Firefox, derivatives) read to offer SearchMob as a
search engine. Mirrors the descriptor produced by the Android Ktor server (`SearchServer.kt`):
the same `ShortName`, `Description`, `InputEncoding`, and the two `<Url>` entries (HTML results
and OpenSearch Suggestions) pointing at the actual bound origin.

The host/port are interpolated into URL `template` attributes; the literal `{searchTerms}` token
is the OpenSearch placeholder the browser fills in at query time, so it is emitted verbatim.
"""

from __future__ import annotations

from html import escape


def build_descriptor(host: str, port: int, *, token: str | None = None) -> bytes:
    """Return the OpenSearch 1.1 XML descriptor body for a server bound on `host:port`.

    `host` and `port` are escaped for XML safety in case a future caller passes something exotic;
    the literal `{searchTerms}` placeholder is preserved (it is part of the OpenSearch template
    grammar, not a value the browser-controlled query can reach).

    `token`, when non-empty, is appended as `&token=<token>` to both `<Url>` templates. This is the
    network-mode access token: a browser that adds SearchMob in network mode needs the token baked
    into the search/suggest templates or its off-loopback requests would be rejected with 403. In
    loopback mode the token is omitted so the templates stay clean.
    """
    safe_host = escape(host, quote=True)
    safe_port = escape(str(port), quote=True)
    origin = f"http://{safe_host}:{safe_port}"
    token_suffix = f"&amp;token={escape(token, quote=True)}" if token else ""
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        "  <ShortName>SearchMob</ShortName>\n"
        "  <Description>Private on-device metasearch</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        f'  <Url type="text/html" template="{origin}/search?q={{searchTerms}}{token_suffix}"/>\n'
        f'  <Url type="application/x-suggestions+json"'
        f' template="{origin}/suggest?q={{searchTerms}}{token_suffix}"/>\n'
        "</OpenSearchDescription>\n"
    )
    return xml.encode("utf-8")

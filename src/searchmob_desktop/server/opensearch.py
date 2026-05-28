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


def build_descriptor(host: str, port: int) -> bytes:
    """Return the OpenSearch 1.1 XML descriptor body for a server bound on `host:port`.

    `host` and `port` are escaped for XML safety in case a future caller passes something exotic;
    the literal `{searchTerms}` placeholder is preserved (it is part of the OpenSearch template
    grammar, not a value the browser-controlled query can reach).
    """
    safe_host = escape(host, quote=True)
    safe_port = escape(str(port), quote=True)
    origin = f"http://{safe_host}:{safe_port}"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        "  <ShortName>SearchMob</ShortName>\n"
        "  <Description>Private on-device metasearch</Description>\n"
        "  <InputEncoding>UTF-8</InputEncoding>\n"
        f'  <Url type="text/html" template="{origin}/search?q={{searchTerms}}"/>\n'
        f'  <Url type="application/x-suggestions+json"'
        f' template="{origin}/suggest?q={{searchTerms}}"/>\n'
        "</OpenSearchDescription>\n"
    )
    return xml.encode("utf-8")

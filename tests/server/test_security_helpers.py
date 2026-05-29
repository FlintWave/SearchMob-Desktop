"""Unit tests for the network-security pure helpers.

`host_header_allowed`, `requires_token`, and `build_descriptor`'s token handling are all pure
functions, so they are tested here without standing up a server or a TestClient. This keeps the
DNS-rebind allowlist policy and the token-gate decision independently verifiable.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from searchmob_desktop.server import host_header_allowed, local_hostnames, requires_token
from searchmob_desktop.server.opensearch import build_descriptor

_OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"


def test_host_header_allowed_loopback_and_bound() -> None:
    assert host_header_allowed("localhost:8787", "192.168.1.50")
    assert host_header_allowed("127.0.0.1", "192.168.1.50")
    assert host_header_allowed("[::1]:8787", "192.168.1.50")
    # The bound host (with or without a port) is allowed.
    assert host_header_allowed("192.168.1.50:8787", "192.168.1.50")
    assert host_header_allowed("192.168.1.50", "192.168.1.50")


def test_host_header_allowed_rejects_foreign_dns() -> None:
    assert not host_header_allowed("evil.com", "192.168.1.50")
    assert not host_header_allowed("evil.com:8787", "192.168.1.50")
    # A different LAN IP than the bound host is not allowed when bound to a concrete address.
    assert not host_header_allowed("10.0.0.9", "192.168.1.50")


def test_host_header_allowed_wildcard_accepts_ip_literals() -> None:
    for bound in ("0.0.0.0", "::", ""):
        assert host_header_allowed("10.0.0.7:8787", bound)
        assert host_header_allowed("[fe80::1]", bound)
        # A DNS name remains rejected under a wildcard bind.
        assert not host_header_allowed("attacker.example", bound)


def test_host_header_allowed_empty_header_is_permitted() -> None:
    # HTTP/1.0 and some probes omit Host; an empty value cannot carry a rebinding target.
    assert host_header_allowed("", "192.168.1.50")
    assert host_header_allowed("   ", "192.168.1.50")


def test_host_header_allowed_accepts_configured_trusted_hostnames() -> None:
    trusted = frozenset({"my-pc.tailnet.ts.net", "my-pc.local"})
    # A configured trusted name is accepted (with or without a port), under any bind.
    assert host_header_allowed("my-pc.tailnet.ts.net", "0.0.0.0", trusted)
    assert host_header_allowed("my-pc.local:8787", "192.168.1.50", trusted)
    # A name not in the trusted set is still rejected.
    assert not host_header_allowed("evil.com", "0.0.0.0", trusted)
    # Without the trusted set, the same friendly name is rejected (regression guard).
    assert not host_header_allowed("my-pc.local", "0.0.0.0")


def test_local_hostnames_are_lowercased_and_nonempty() -> None:
    names = local_hostnames()
    # Best-effort: may be empty on an odd host, but whatever is returned is lowercased and clean.
    for name in names:
        assert name == name.strip().lower()
        assert name


def test_requires_token_only_for_nonloopback_with_token() -> None:
    # No token configured -> never required, regardless of client.
    assert not requires_token("203.0.113.5", None)
    assert not requires_token("203.0.113.5", "")
    # Token configured -> loopback exempt, everyone else required.
    assert not requires_token("127.0.0.1", "tok")
    assert not requires_token("localhost", "tok")
    assert not requires_token("::1", "tok")
    assert requires_token("192.168.1.10", "tok")
    assert requires_token("203.0.113.5", "tok")


def _templates(body: bytes) -> dict[str, str]:
    root = ET.fromstring(body)
    return {
        url.attrib["type"]: url.attrib["template"]
        for url in root.findall(f"{{{_OPENSEARCH_NS}}}Url")
    }


def test_build_descriptor_appends_token() -> None:
    templates = _templates(build_descriptor("192.168.1.50", 8787, token="abc123"))
    assert templates["text/html"] == (
        "http://192.168.1.50:8787/search?q={searchTerms}&token=abc123"
    )
    assert templates["application/x-suggestions+json"] == (
        "http://192.168.1.50:8787/suggest?q={searchTerms}&token=abc123"
    )


def test_build_descriptor_omits_token_when_absent() -> None:
    for token in (None, ""):
        body = build_descriptor("127.0.0.1", 8787, token=token)
        assert b"token=" not in body


def test_build_descriptor_escapes_ampersand_in_xml() -> None:
    # The raw XML must escape the separator as &amp; so the descriptor is well-formed; ElementTree
    # round-trips it back to a single & in the attribute value (asserted above).
    raw = build_descriptor("127.0.0.1", 8787, token="t").decode("utf-8")
    assert "&amp;token=t" in raw
    assert "&token=" not in raw  # never a bare, unescaped ampersand

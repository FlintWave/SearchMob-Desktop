"""Served engine status: the per-engine outcome line is shown to the loopback owner only.

A network/LAN visitor must never see engine diagnostics, mirroring how the editing controls are
owner-gated. The metasearch fake returns an `AggregateOutcome` carrying per-engine outcomes so the
status line has data to render.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from searchmob_desktop.engines import (
    AggregateOutcome,
    EngineContext,
    EngineOutcome,
    SearchResult,
)
from searchmob_desktop.server.app import build_app


async def _metasearch(_ctx: EngineContext, _engines: object) -> AggregateOutcome:
    results = [SearchResult(title="One", url="https://a.example/1", snippet="s", engine="alpha")]
    engines = (
        EngineOutcome("alpha", "contributed", 1),
        EngineOutcome("beta", "failed", 0),
    )
    return AggregateOutcome(results, engines)


def _app() -> object:
    return build_app(
        [lambda _c, _ctx: []],
        bound_port_getter=lambda: 8787,
        bound_host_getter=lambda: "0.0.0.0",
        metasearch=_metasearch,  # type: ignore[arg-type]
        # `_is_owner` requires a rules saver wired plus a loopback client.
        ranking_rules_saver=lambda _r: True,
        host_allowlist_enabled=False,
    )


def test_owner_sees_engine_status_line() -> None:
    client = TestClient(_app(), client=("127.0.0.1", 9))  # type: ignore[arg-type]
    html = client.get("/search", params={"q": "anything"}).text
    assert "engines responded" in html
    assert 'class="engine-status' in html


def test_lan_visitor_sees_no_engine_status() -> None:
    client = TestClient(_app(), client=("10.0.0.5", 9))  # type: ignore[arg-type]
    html = client.get("/search", params={"q": "anything"}).text
    assert "engines responded" not in html
    # The stylesheet always defines `.engine-status`; assert the rendered element is absent, not the
    # CSS rule.
    assert '<details class="engine-status' not in html

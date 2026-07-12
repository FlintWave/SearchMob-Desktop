"""Shared test fixtures.

The i18n catalog carries a per-request locale override in a `ContextVar` that the served-page
renderers set so nested `tr()` calls localize without threading `locale=` everywhere. In production
each request runs in its own asyncio task, so that override is naturally isolated per request. The
synchronous test runner, however, shares one context across tests, so an override set by a server
test would otherwise leak into a later test's bare `tr()`. This autouse fixture clears it at each
test boundary, reproducing the per-request isolation the renderers rely on.
"""

from __future__ import annotations

import pytest

from searchmob_desktop.engines import proxy
from searchmob_desktop.i18n import set_request_locale


@pytest.fixture(autouse=True)
def _reset_request_locale() -> None:
    set_request_locale(None)


@pytest.fixture(autouse=True)
def _no_politeness_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the per-host politeness interval and reset its slot table between tests.

    The process-wide spacing exists for real upstream hosts; the test suite hammers a handful of
    mocked hosts hundreds of times and would otherwise serialize a real 1-second sleep per
    request. The politeness test that exercises the spacing sets its own interval locally.
    """
    monkeypatch.setattr(proxy, "_POLITENESS_INTERVAL_SECONDS", 0.0)
    proxy._next_slot_by_host.clear()

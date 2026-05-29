"""Contextual Wikipedia summary box: query gating, relevance, parsing, and fail-soft behavior."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.engines.wiki_summary import (
    SummaryBox,
    fetch_summary,
    is_confident_match,
    is_entity_like_query,
)

_OPENSEARCH = "https://en.wikipedia.org/w/api.php"
_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/Mount_Everest"


def _opensearch(*titles: str) -> list[object]:
    return ["q", list(titles), [""] * len(titles), [""] * len(titles)]


def _summary(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "type": "standard",
        "title": "Mount Everest",
        "description": "Earth's highest mountain",
        "extract": "Mount Everest is Earth's highest mountain above sea level.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Mount_Everest"}},
        "thumbnail": {"source": "https://upload.wikimedia.org/everest.jpg"},
    }
    base.update(over)
    return base


def test_entity_like_query_gate() -> None:
    assert is_entity_like_query("mount everest")
    assert is_entity_like_query("Python")
    assert not is_entity_like_query("")
    assert not is_entity_like_query(
        "how do I install python on ubuntu linux today"
    )  # too many tokens
    assert not is_entity_like_query("https://example.com")
    assert not is_entity_like_query("example.com")  # navigational, single dotted token


def test_confident_match() -> None:
    assert is_confident_match("everest", "Mount Everest")  # subset
    assert is_confident_match("mount everest", "Mount Everest (mountain)")  # parenthetical dropped
    assert is_confident_match("the matrix", "The Matrix")
    assert not is_confident_match("everest", "George Mallory")  # unrelated


@pytest.mark.asyncio
@respx.mock
async def test_happy_path_returns_box() -> None:
    respx.get(_OPENSEARCH).mock(return_value=httpx.Response(200, json=_opensearch("Mount Everest")))
    respx.get(_SUMMARY).mock(return_value=httpx.Response(200, json=_summary()))
    async with make_privacy_client() as client:
        box = await fetch_summary(client, "mount everest")
    assert isinstance(box, SummaryBox)
    assert box.title == "Mount Everest"
    assert box.description == "Earth's highest mountain"
    assert "highest mountain" in box.extract
    assert box.url == "https://en.wikipedia.org/wiki/Mount_Everest"
    assert box.thumbnail_url == "https://upload.wikimedia.org/everest.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_disambiguation_is_rejected() -> None:
    respx.get(_OPENSEARCH).mock(return_value=httpx.Response(200, json=_opensearch("Mount Everest")))
    respx.get(_SUMMARY).mock(return_value=httpx.Response(200, json=_summary(type="disambiguation")))
    async with make_privacy_client() as client:
        assert await fetch_summary(client, "mount everest") is None


@pytest.mark.asyncio
@respx.mock
async def test_low_confidence_title_yields_no_box() -> None:
    # OpenSearch returns an unrelated top title; the relevance gate rejects it before the REST call.
    respx.get(_OPENSEARCH).mock(return_value=httpx.Response(200, json=_opensearch("Banana bread")))
    summary_route = respx.get(_SUMMARY).mock(return_value=httpx.Response(200, json=_summary()))
    async with make_privacy_client() as client:
        assert await fetch_summary(client, "mount everest") is None
    assert not summary_route.called  # never reached the summary endpoint


@pytest.mark.asyncio
@respx.mock
async def test_non_entity_query_skips_network() -> None:
    route = respx.get(_OPENSEARCH).mock(return_value=httpx.Response(200, json=_opensearch("X")))
    async with make_privacy_client() as client:
        assert await fetch_summary(client, "what is the best way to learn rust programming") is None
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_fail_soft_on_http_error() -> None:
    respx.get(_OPENSEARCH).mock(return_value=httpx.Response(200, json=_opensearch("Mount Everest")))
    respx.get(_SUMMARY).mock(return_value=httpx.Response(404))
    async with make_privacy_client() as client:
        assert await fetch_summary(client, "mount everest") is None

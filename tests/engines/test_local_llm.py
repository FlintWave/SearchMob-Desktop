"""Local-LLM detection, prompt grounding, and answer generation (all mocked, no real model)."""

from __future__ import annotations

import httpx
import pytest
import respx

from searchmob_desktop.engines.local_llm import (
    LlmConfig,
    build_messages,
    detect_backends,
    generate_answer,
)
from searchmob_desktop.engines.types import SearchResult

_RESULTS = [
    SearchResult(
        "Mount Everest", "https://en.wikipedia.org/wiki/Everest", "Highest mountain.", "x"
    ),
    SearchResult("K2", "https://example.com/k2", "Second highest.", "x"),
]


def test_config_ready_requires_enabled_url_and_model() -> None:
    assert not LlmConfig().ready
    assert not LlmConfig(enabled=True).ready
    assert not LlmConfig(enabled=True, base_url="http://127.0.0.1:11434/v1").ready
    assert LlmConfig(enabled=True, base_url="http://127.0.0.1:11434/v1", model="llama3").ready


def test_build_messages_grounds_on_numbered_sources() -> None:
    messages = build_messages("tallest mountain", _RESULTS)
    assert messages[0]["role"] == "system"
    assert "[1]" in messages[0]["content"] or "cite" in messages[0]["content"].lower()
    user = messages[1]["content"]
    assert "tallest mountain" in user
    assert "[1] Mount Everest" in user
    assert "[2] K2" in user
    assert "https://en.wikipedia.org/wiki/Everest" in user


@pytest.mark.asyncio
@respx.mock
async def test_detect_backends_finds_ollama_and_lmstudio() -> None:
    respx.get("http://127.0.0.1:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})
    )
    respx.get("http://127.0.0.1:1234/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "qwen2.5-7b"}]})
    )
    backends = await detect_backends()
    by_name = {b.name: b for b in backends}
    assert set(by_name) == {"Ollama", "LM Studio"}
    assert by_name["Ollama"].base_url == "http://127.0.0.1:11434/v1"
    assert by_name["Ollama"].models == ("llama3:latest",)
    assert by_name["LM Studio"].models == ("qwen2.5-7b",)


@pytest.mark.asyncio
@respx.mock
async def test_detect_backends_skips_unreachable_or_empty() -> None:
    respx.get("http://127.0.0.1:11434/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    respx.get("http://127.0.0.1:1234/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    assert await detect_backends() == []


@pytest.mark.asyncio
@respx.mock
async def test_generate_answer_returns_assistant_text() -> None:
    route = respx.post("http://127.0.0.1:11434/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Everest is tallest [1]."}}
                ]
            },
        )
    )
    config = LlmConfig(enabled=True, base_url="http://127.0.0.1:11434/v1", model="llama3")
    answer = await generate_answer(config, "tallest mountain", _RESULTS)
    assert answer == "Everest is tallest [1]."
    # The request actually carried the chosen model and grounded messages.
    sent = route.calls.last.request
    assert b'"model": "llama3"' in sent.content or b'"model":"llama3"' in sent.content


@pytest.mark.asyncio
async def test_generate_answer_none_when_not_ready() -> None:
    assert await generate_answer(LlmConfig(), "q", _RESULTS) is None
    ready_but_no_results = LlmConfig(
        enabled=True, base_url="http://127.0.0.1:11434/v1", model="llama3"
    )
    assert await generate_answer(ready_but_no_results, "q", []) is None
    assert await generate_answer(ready_but_no_results, "   ", _RESULTS) is None


@pytest.mark.asyncio
@respx.mock
async def test_generate_answer_fail_soft_on_server_error() -> None:
    respx.post("http://127.0.0.1:11434/v1/chat/completions").mock(return_value=httpx.Response(500))
    config = LlmConfig(enabled=True, base_url="http://127.0.0.1:11434/v1", model="llama3")
    assert await generate_answer(config, "q", _RESULTS) is None

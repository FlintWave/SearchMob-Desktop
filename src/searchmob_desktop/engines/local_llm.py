"""Optional local-LLM answer box: a synthesized, cited answer from a model running on this machine.

This is the one feature that never touches the network. It talks only to a language-model server
already running on loopback (Ollama on `:11434`, LM Studio on `:1234`), both of which expose the
OpenAI-compatible `/v1/chat/completions` endpoint. The query and the on-device result snippets are
sent to that local server and nowhere else; if no server is running, the feature stays invisible.

Everything is fail-soft and off by default. Detection probes the two known loopback ports; if
neither answers, `detect_backends()` returns an empty list and the UI never shows the box. Answer
generation is grounded: the prompt feeds the model the top result snippets and asks it to answer
using only those, citing them as `[n]`, so the output is a summary of the user's own results rather
than the model's free-floating memory.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from searchmob_desktop.engines.types import SearchResult

# Known local model servers, probed in order. Each exposes an OpenAI-compatible API under `/v1`.
# (display name, origin, models-list path). Loopback only, by design.
_BACKENDS: tuple[tuple[str, str, str], ...] = (
    ("Ollama", "http://127.0.0.1:11434", "/api/tags"),
    ("LM Studio", "http://127.0.0.1:1234", "/v1/models"),
)

# Bound everything: a local model can stream a lot, and the probe/answer should never hang the UI.
# The answer timeout is generous because a large model (20B+) can take a while on a cold start
# (loading weights into memory) before the first token; a tighter bound would silently drop the box.
_PROBE_TIMEOUT = 1.5
_ANSWER_TIMEOUT = 180.0
# For streaming, the timeout is the gap allowed between tokens (reset by each one), not a total cap.
# It is generous so a big model that is slow to load before the first token is not dropped, while a
# genuinely dead connection still eventually times out.
_STREAM_READ_TIMEOUT = 120.0
_MAX_ANSWER_BYTES = 2 * 1024 * 1024
# How many results to ground the answer on, and how much of each snippet to include.
_MAX_SOURCES = 6
_MAX_SNIPPET_CHARS = 400


@dataclass(frozen=True)
class LlmBackend:
    """A detected local model server and the models it reports."""

    name: str
    base_url: str  # OpenAI-compatible base, e.g. "http://127.0.0.1:11434/v1"
    models: tuple[str, ...]


@dataclass(frozen=True)
class LlmConfig:
    """The user's local-AI settings. `enabled` off (the default) keeps the feature invisible."""

    enabled: bool = False
    base_url: str = ""
    model: str = ""

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.base_url) and bool(self.model)


def _local_client(timeout: float) -> httpx.AsyncClient:
    """An httpx client for loopback model servers: no proxy, bounded timeout, no redirects.

    `trust_env=False` so a stray HTTP(S)_PROXY in the environment can never intercept what is meant
    to be a purely on-device call. Redirects are off because a loopback API has no reason to issue
    one, and following it could leave the loopback origin.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        trust_env=False,
    )


def _models_from_tags(payload: object) -> tuple[str, ...]:
    """Extract model names from either Ollama's `/api/tags` or an OpenAI `/v1/models` body."""
    if not isinstance(payload, dict):
        return ()
    names: list[str] = []
    # Ollama: {"models": [{"name": "llama3:latest"}, ...]}
    for item in payload.get("models", []) or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    # OpenAI / LM Studio: {"data": [{"id": "..."}]}
    for item in payload.get("data", []) or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            names.append(item["id"])
    # Preserve order, drop duplicates (dict keys keep insertion order in 3.7+).
    return tuple(dict.fromkeys(names))


async def detect_backends(timeout: float = _PROBE_TIMEOUT) -> list[LlmBackend]:
    """Probe the known loopback ports and return the backends that respond, with their models.

    Fail-soft: a port that is closed, slow, or returns junk is simply skipped. The returned
    `base_url` is the OpenAI-compatible base (`<origin>/v1`) used for chat completions.
    """
    found: list[LlmBackend] = []
    async with _local_client(timeout) as client:
        for name, origin, tags_path in _BACKENDS:
            try:
                resp = await client.get(origin + tags_path)
                resp.raise_for_status()
                payload = resp.json()
            except (httpx.HTTPError, ValueError):
                continue
            models = _models_from_tags(payload)
            if models:
                found.append(LlmBackend(name=name, base_url=origin + "/v1", models=models))
    return found


def build_messages(query: str, results: list[SearchResult]) -> list[dict[str, str]]:
    """Build the grounded chat prompt: a system instruction plus the numbered result snippets.

    The model is told to answer only from the provided sources and cite them as `[n]`, so the box
    summarizes the user's own results instead of the model's training data. Sources are capped so
    the prompt stays small and fast for a local model.
    """
    sources: list[str] = []
    for i, r in enumerate(results[:_MAX_SOURCES], start=1):
        snippet = (r.snippet or "").strip()[:_MAX_SNIPPET_CHARS]
        sources.append(f"[{i}] {r.title}\n{r.url}\n{snippet}")
    sources_block = "\n\n".join(sources) if sources else "(no results)"
    system = (
        "You are a concise search assistant running locally on the user's own computer. "
        "Answer the user's query using only the numbered sources provided. "
        "Cite the sources you use inline as [1], [2], etc. "
        "If the sources do not contain the answer, say so plainly. "
        "Keep it to a short paragraph or two of plain text, no markdown headings."
    )
    user = f"Query: {query}\n\nSources:\n{sources_block}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _answer_from_completion(payload: object) -> str | None:
    """Pull the assistant text out of an OpenAI-compatible chat-completion body."""
    if not isinstance(payload, dict):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    return None


async def generate_answer(
    config: LlmConfig,
    query: str,
    results: list[SearchResult],
    timeout: float = _ANSWER_TIMEOUT,
) -> str | None:
    """Ask the configured local model for a grounded answer, or None on any problem.

    Returns None when the feature is not ready, the query is blank, there are no results to ground
    on, or the local server errors. Non-streaming for a single, simple response; the body is
    size-bounded so a runaway generation cannot exhaust memory.
    """
    if not config.ready or not query.strip() or not results:
        return None
    body = {
        "model": config.model,
        "messages": build_messages(query, results),
        "stream": False,
        "temperature": 0.2,
    }
    url = config.base_url.rstrip("/") + "/chat/completions"
    try:
        async with _local_client(timeout) as client, client.stream("POST", url, json=body) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > _MAX_ANSWER_BYTES:
                    return None
                chunks.append(chunk)
        payload = json.loads(b"".join(chunks).decode("utf-8", "replace"))
    except (httpx.HTTPError, ValueError):
        return None
    return _answer_from_completion(payload)


def _delta_from_chunk(payload: object) -> str:
    """Pull the incremental text from one OpenAI streaming chunk (`choices[0].delta.content`)."""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    return ""


async def stream_answer(
    config: LlmConfig,
    query: str,
    results: list[SearchResult],
    on_delta: Callable[[str], None],
    read_timeout: float = _STREAM_READ_TIMEOUT,
) -> str | None:
    """Stream a grounded answer token-by-token, calling `on_delta` for each piece, return the whole.

    Streaming matters for local models: a large model can take tens of seconds to load and begin
    replying, and non-streaming would show nothing until the entire answer is generated (which reads
    as a hang). With streaming the answer appears as it is produced, and the timeout is a per-read
    gap (between tokens), not a total cap, so a slow-but-progressing generation is never cut off.

    Returns the full text (also the accumulation of the deltas), or None when not ready / blank /
    no results / the server errors before any text arrives. Any text received before an error is
    returned rather than discarded.
    """
    if not config.ready or not query.strip() or not results:
        return None
    body = {
        "model": config.model,
        "messages": build_messages(query, results),
        "stream": True,
        "temperature": 0.2,
    }
    url = config.base_url.rstrip("/") + "/chat/completions"
    # Connect quickly, but allow a long gap before the first token (model load); a token resets it.
    timeout = httpx.Timeout(read_timeout, connect=10.0)
    parts: list[str] = []
    total = 0
    try:
        async with (
            httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as (client),
            client.stream("POST", url, json=body) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                piece = _delta_from_chunk(chunk)
                if piece:
                    total += len(piece)
                    if total > _MAX_ANSWER_BYTES:
                        break
                    parts.append(piece)
                    on_delta(piece)
    except (httpx.HTTPError, ValueError):
        # Return whatever streamed before the error rather than losing a partial answer.
        text = "".join(parts).strip()
        return text or None
    text = "".join(parts).strip()
    return text or None

"""Search-suggestions providers for the SearchMob Desktop `/suggest` endpoint.

Mirrors the Android `server/suggest/SuggestionsProvider.kt` package:

- `NoSuggestionsProvider`: always returns `[]`. The default when neither
  history nor upstream is wired.
- `HistorySuggestionsProvider`: prefix-matches the user's local encrypted
  history. Returns `[]` when history is opted out or the vault is locked.
- `UpstreamSuggestionsProvider`: fetches DuckDuckGo's autocomplete endpoint
  through the existing privacy-proxy `httpx.AsyncClient`. Off by default
  because it leaks the partial query upstream; the composite asks for it
  only when the user explicitly turns the toggle on.
- `CompositeSuggestionsProvider`: always queries history; queries upstream
  only when an `upstream_enabled()` lambda returns True (read live at call
  time so a settings toggle takes effect without restarting the server).
  Merges local-first, dedups case-insensitively, caps at `MAX_SUGGESTIONS`.

Every provider is fail-soft: any error, timeout, or unavailable source
returns an empty list rather than raising, so the address bar never hangs.
"""

from __future__ import annotations

from searchmob_desktop.suggest.providers import (
    MAX_SUGGESTIONS,
    CompositeSuggestionsProvider,
    HistorySuggestionsProvider,
    NoSuggestionsProvider,
    UpstreamSuggestionsProvider,
)

__all__ = [
    "MAX_SUGGESTIONS",
    "CompositeSuggestionsProvider",
    "HistorySuggestionsProvider",
    "NoSuggestionsProvider",
    "UpstreamSuggestionsProvider",
]

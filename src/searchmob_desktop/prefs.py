"""Persistent user preferences for SearchMob Desktop.

These are non-secret settings: theme, per-engine toggles, history opt-in,
network mode, the upstream-suggestions toggle, the update-check toggle, and
the last-update-check timestamp. Sensitive material (API keys, history rows)
lives in the encrypted vault (`data/`) and never passes through this store.

Default path resolves under `platformdirs.user_config_dir("SearchMob",
"FlintWave")` so settings persist alongside the user's other app configs.
Writes are atomic (tmp file + `os.replace`) so a crash mid-write cannot leave
a half-written `prefs.json` on disk.

JSON loading is lenient: unknown fields are ignored and missing fields fall
back to the dataclass defaults so older `prefs.json` files keep loading after
a schema bump.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Protocol

import platformdirs

from searchmob_desktop.fsperms import restrict_dir, restrict_file

__all__ = [
    "JsonPreferencesStore",
    "PreferencesStore",
    "UserPreferences",
    "default_preferences_path",
]


def default_preferences_path() -> Path:
    """The on-disk location for `prefs.json` under the platform user-config dir."""
    return Path(platformdirs.user_config_dir("SearchMob", "FlintWave")) / "prefs.json"


@dataclass(frozen=True, slots=True)
class UserPreferences:
    """The user-facing settings the desktop app reads on every request.

    Defaults match the Android `UserPreferences.kt`: store-nothing default
    (history off), loopback-only (network access off), no upstream
    suggestions, but DO check for updates (opt-out, not opt-in).
    """

    theme: str = "system"
    # Two-slot theming: `theme` is the mode (light/dark/system); these pick which named theme fills
    # the light slot and the dark slot. Defaults keep the original SearchMob look for upgraders.
    light_theme: str = "searchmob-light"
    dark_theme: str = "searchmob-dark"
    # Base interface font size, in points (12pt default, stepped by 2 via the A-/A+ controls).
    font_point_size: int = 12
    history_enabled: bool = False
    # Learn a bounded ranking boost from the owner's own result clicks (off by default, opt-in via
    # the first-run wizard or Settings). The learned model is stored encrypted in the vault and is
    # never trained by, nor applied for, network clients. See engines/rank/personalize.py.
    personalization_enabled: bool = False
    network_access_enabled: bool = False
    # Shared secret appended as a `?token=` query param to gate the search/suggest routes when the
    # server is reachable off-loopback. Empty means "not yet generated"; it is minted lazily the
    # first time network access is turned on and then reused so re-enabling keeps the same token.
    network_access_token: str = ""
    # Extra hostnames (besides loopback names and IP literals) that the server's Host-header
    # allowlist accepts, so a browser can reach SearchMob by a friendly name in network mode, e.g.
    # a Tailscale MagicDNS name or an mDNS `<host>.local`. Lowercased, no scheme/port. The machine's
    # own hostname is allowed automatically; this is for names that machine cannot self-detect.
    network_hostnames: tuple[str, ...] = ()
    upstream_suggestions_enabled: bool = False
    # Show a contextual Wikipedia summary box above results for entity-like queries. Adds at most
    # one extra outbound call per search to Wikipedia (which is already a search engine here).
    summary_enabled: bool = True
    # Result sort order: "fresh" (freshness+relevance blend, default), "date", or "relevance".
    sort_mode: str = "fresh"
    # AI-slop / low-quality content filter: "downrank" (default, on), "hide", or "off".
    ai_slop_mode: str = "downrank"
    # Extra domains the MCP `web_search` tool excludes from results handed to a local AI agent (the
    # agent's own dedicated scope), on top of the always-applied AI-slop blocklist. Non-secret and
    # kept here (not the encrypted vault) on purpose, so the filter still works when the headless
    # MCP subprocess cannot unlock a zero-knowledge vault. Lowercased registrable domains, no path.
    agent_safety_excludes: tuple[str, ...] = ()
    # Optional local-LLM answer box. Off by default and only ever talks to a model server running on
    # this machine (Ollama/LM Studio); nothing leaves the device. `llm_base_url` is the OpenAI-
    # compatible endpoint base; `llm_model` is the chosen model. Both empty until the user detects
    # and picks one.
    llm_enabled: bool = False
    llm_base_url: str = ""
    llm_model: str = ""
    update_check_enabled: bool = True
    last_update_check_ms: int = 0
    # The newest published release the last update check found (empty when none / up to date). These
    # drive the in-app and served-page "update available" banners and the tray notification so a
    # found update survives a restart until a later check supersedes or clears it. Non-secret: just
    # a version string and the release URL. Set/cleared via update.reconcile_pending_update.
    pending_update_version: str = ""
    pending_update_url: str = ""
    # Set once the first-run setup wizard has been completed or skipped, so it never reappears.
    onboarding_completed: bool = False
    # The onboarding revision the user last saw. The wizard re-appears once after an update that
    # adds a step worth showing (when this is below the app's current ONBOARDING_VERSION), so
    # existing users discover new opt-in features instead of only fresh installs seeing them.
    onboarding_version: int = 0
    engine_enabled: Mapping[str, bool] = field(default_factory=dict)

    def with_update_check_stamped(self, now_ms: int) -> UserPreferences:
        """Return a copy with `last_update_check_ms` bumped to `now_ms`."""
        return replace(self, last_update_check_ms=now_ms)


class PreferencesStore(Protocol):
    """Protocol for loading and persisting `UserPreferences`."""

    def load(self) -> UserPreferences: ...

    def save(self, prefs: UserPreferences) -> None: ...


class JsonPreferencesStore:
    """File-backed `PreferencesStore` that round-trips JSON atomically.

    `load()` returns the dataclass defaults when the file does not exist or
    fails to parse, so the very first launch never crashes. `save()` writes
    to a sibling temp file and `os.replace`s it onto the real path so a
    partially-written file can never be observed by another reader.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else default_preferences_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UserPreferences:
        if not self._path.is_file():
            return UserPreferences()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return UserPreferences()
        if not isinstance(data, dict):
            return UserPreferences()
        return _from_dict(data)

    def save(self, prefs: UserPreferences) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        restrict_dir(self._path.parent)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = json.dumps(asdict(prefs), indent=2, sort_keys=True)
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)
        # Owner-only: prefs are not secret, but leaking the user's engine/network/update choices to
        # other local accounts is needless. Best-effort (no-op where chmod is unsupported).
        restrict_file(self._path)


def _from_dict(data: dict[str, Any]) -> UserPreferences:
    """Build a `UserPreferences` from a possibly-old JSON dict, lenient on missing fields."""
    known = {f.name for f in fields(UserPreferences)}
    filtered: dict[str, Any] = {}
    for key in known:
        if key not in data:
            continue
        value = data[key]
        if key == "engine_enabled":
            if isinstance(value, dict):
                filtered[key] = {str(k): bool(v) for k, v in value.items()}
            continue
        if key in ("network_hostnames", "agent_safety_excludes"):
            if isinstance(value, (list, tuple)):
                filtered[key] = tuple(
                    str(item).strip().lower() for item in value if str(item).strip()
                )
            continue
        filtered[key] = value
    return UserPreferences(**filtered)

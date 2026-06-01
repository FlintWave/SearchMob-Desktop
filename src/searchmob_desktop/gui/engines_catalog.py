"""Catalog of engines surfaced by the GUI settings checklist.

Two pieces of metadata live here: the user-facing display name and whether the engine needs a
BYO key. The mapping mirrors the Android `EngineCatalog` so the settings UI shows the same set.
Pure data; no PySide6 imports.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineEntry:
    """One row in the engines settings checklist."""

    id: str
    display_name: str
    requires_api_key: bool


ENGINE_CATALOG: tuple[EngineEntry, ...] = (
    EngineEntry(id="duckduckgo", display_name="DuckDuckGo", requires_api_key=False),
    EngineEntry(id="wikipedia", display_name="Wikipedia", requires_api_key=False),
    EngineEntry(id="mojeek", display_name="Mojeek (HTML)", requires_api_key=False),
    EngineEntry(id="marginalia", display_name="Marginalia", requires_api_key=False),
    EngineEntry(id="mwmbl", display_name="Mwmbl", requires_api_key=False),
    EngineEntry(id="brave", display_name="Brave Search API", requires_api_key=True),
    EngineEntry(id="mojeek-api", display_name="Mojeek API", requires_api_key=True),
    EngineEntry(id="kagi-api", display_name="Kagi (API)", requires_api_key=True),
)


# Default enabled-state per engine: the free engines are on out of the box, while the BYO-key
# engines start off (they cannot do anything until you add a key, so checking them by default would
# only ever be a no-op or a confusing "enabled but silent" engine).
_DEFAULT_ENABLED: dict[str, bool] = {e.id: not e.requires_api_key for e in ENGINE_CATALOG}


def is_engine_enabled(engine_id: str, engine_enabled: dict[str, bool] | None) -> bool:
    """Resolve an engine's enabled state, falling back to its default when the map has no entry.

    Free engines default on (a fresh profile searches them without opt-in); key-requiring engines
    default off (you turn one on when you add its key). An explicit entry in the map always wins.
    """
    default = _DEFAULT_ENABLED.get(engine_id, True)
    if not engine_enabled:
        return default
    return engine_enabled.get(engine_id, default)

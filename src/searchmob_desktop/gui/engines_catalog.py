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
)


def is_engine_enabled(engine_id: str, engine_enabled: dict[str, bool] | None) -> bool:
    """Default-on lookup: an engine missing from the map counts as enabled.

    Matches the Android `isEngineEnabled` so a fresh profile uses every free engine without the
    user having to opt each one in.
    """
    if not engine_enabled:
        return True
    return engine_enabled.get(engine_id, True)

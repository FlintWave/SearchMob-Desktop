"""CLI command coverage: `search`, `_build_engines`, and `vault status`.

These exercise the Typer assembly in `searchmob_desktop.cli` without any network: `aggregate` and
the vault key reader are monkeypatched so no engine ever issues an HTTP request and the vault is
never touched. The `--version` / `--help` paths are covered in `tests/test_smoke.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import searchmob_desktop.cli as cli
from searchmob_desktop.cli import _build_engines, app
from searchmob_desktop.engines import SearchResult


def test_search_happy_path_prints_table_and_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """`search "<query>"` prints the merged results table and exits 0 with no network."""
    results = [
        SearchResult(title="First hit", url="https://example.com/a", snippet="", engine="ddg"),
        SearchResult(title="Second hit", url="https://example.com/b", snippet="", engine="wiki"),
    ]

    async def _fake_aggregate(_ctx: object, _engines: object) -> list[SearchResult]:
        return results

    monkeypatch.setattr(cli, "aggregate", _fake_aggregate)
    monkeypatch.setattr(cli, "_build_engines", lambda: [])

    out = CliRunner().invoke(app, ["search", "hello world"])
    assert out.exit_code == 0, out.output
    assert "First hit" in out.output
    assert "Second hit" in out.output
    assert "https://example.com/a" in out.output


def test_search_no_results_exits_one_with_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """The empty-results path prints "No results" and exits 1."""

    async def _empty(_ctx: object, _engines: object) -> list[SearchResult]:
        return []

    monkeypatch.setattr(cli, "aggregate", _empty)
    monkeypatch.setattr(cli, "_build_engines", lambda: [])

    out = CliRunner().invoke(app, ["search", "nothing matches"])
    assert out.exit_code == 1, out.output
    assert "No results" in out.output


def test_build_engines_returns_five_free_engines_with_no_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no resolvable BYO key, only the five free engine callables are assembled."""
    monkeypatch.setattr(cli, "read_vault_api_keys", dict)
    # Belt and braces: ensure env-var fallback inside resolve_api_key sees nothing either.
    for var in ("SEARCHMOB_BRAVE_API_KEY", "SEARCHMOB_MOJEEK_API_KEY", "SEARCHMOB_KAGI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    engines = _build_engines()
    assert len(engines) == 5


def test_build_engines_appends_keyed_engine_when_vault_has_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Kagi key in the vault adds a sixth (keyed) engine to the assembled list."""
    monkeypatch.setattr(cli, "read_vault_api_keys", lambda: {"kagi_api_key": "secret-kagi"})
    for var in ("SEARCHMOB_BRAVE_API_KEY", "SEARCHMOB_MOJEEK_API_KEY", "SEARCHMOB_KAGI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    engines = _build_engines()
    assert len(engines) == 6


def test_vault_status_runs_and_exits_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`vault status` prints the mode/state/metadata path and exits 0 against a tmp location."""
    from searchmob_desktop.data.bootstrap_metadata_store import BootstrapMetadataStore

    metadata_path = tmp_path / "bootstrap.json"
    real_init = BootstrapMetadataStore.__init__

    def _patched_init(self: BootstrapMetadataStore, path: Path | None = None) -> None:
        real_init(self, metadata_path)

    monkeypatch.setattr(BootstrapMetadataStore, "__init__", _patched_init)

    out = CliRunner().invoke(app, ["vault", "status"])
    assert out.exit_code == 0, out.output
    # Uninitialized vault: no metadata file yet, so the status reports that plus the metadata-file
    # line. Rich wraps the long tmp path across lines, so we assert on the label and the unique
    # path stem rather than the unwrapped string.
    assert "uninitialized" in out.output.lower()
    assert "metadata file:" in out.output.lower()
    assert tmp_path.name in out.output  # the unique pytest tmp dir name is short enough not to wrap

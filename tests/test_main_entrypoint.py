"""The package entry point (`python -m searchmob_desktop`) is what the native installers launch.

With no arguments it must open the GUI (not the CLI, which would print help and exit, leaving a
desktop launch with no visible window). With arguments it must defer to the CLI so headless
`python -m searchmob_desktop search ...` still works. These tests stub both targets so neither a
real Qt window nor a network search is created.
"""

from __future__ import annotations

import sys

import pytest

import searchmob_desktop.__main__ as entry


def test_no_args_launches_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    """No CLI args => open the GUI window (and propagate its exit code)."""
    called: dict[str, object] = {}

    def _fake_run_gui(argv: object = None) -> int:
        called["gui"] = True
        return 0

    monkeypatch.setattr("searchmob_desktop.gui.app.run_gui", _fake_run_gui)
    monkeypatch.setattr(sys, "argv", ["searchmob_desktop"])

    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 0
    assert called.get("gui") is True


def test_args_defer_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arguments present => behave like the CLI rather than opening the GUI."""
    called: dict[str, object] = {}

    monkeypatch.setattr("searchmob_desktop.cli.main", lambda: called.setdefault("cli", True))
    monkeypatch.setattr(
        "searchmob_desktop.gui.app.run_gui",
        lambda argv=None: called.setdefault("gui", True),
    )
    monkeypatch.setattr(sys, "argv", ["searchmob_desktop", "search", "hi"])

    entry.main()
    assert called.get("cli") is True
    assert "gui" not in called


def test_missing_gui_extra_falls_back_to_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a headless install (no PySide6), a no-arg launch falls back to the CLI."""
    called: dict[str, object] = {}

    import builtins

    real_import = builtins.__import__

    def _no_gui_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "searchmob_desktop.gui.app":
            raise ImportError("PySide6 not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_gui_import)
    monkeypatch.setattr("searchmob_desktop.cli.main", lambda: called.setdefault("cli", True))
    monkeypatch.setattr(sys, "argv", ["searchmob_desktop"])

    entry.main()
    assert called.get("cli") is True

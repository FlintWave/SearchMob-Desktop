"""About dialog carries the icon attribution and the trademark/non-affiliation disclaimer."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.gui.about_dialog import AboutDialog


def _all_label_text(widget: object) -> str:
    from PySide6.QtWidgets import QLabel

    return "\n".join(label.text() for label in widget.findChildren(QLabel))  # type: ignore[attr-defined]


def test_about_shows_attribution_and_trademark_disclaimer(qapp: object) -> None:
    text = _all_label_text(AboutDialog())
    assert "Freepik" in text  # Flaticon attribution
    assert "not affiliated" in text.lower()
    # Names the marks it references so the nominative use is explicit.
    for mark in ("DuckDuckGo", "Brave", "Kagi"):
        assert mark in text


def test_about_has_a_link_to_the_android_app(qapp: object) -> None:
    from PySide6.QtWidgets import QPushButton

    from searchmob_desktop.gui.about_dialog import ANDROID_URL

    dialog = AboutDialog()
    labels = [b.text() for b in dialog.findChildren(QPushButton)]
    assert any("Android" in t for t in labels)
    assert ANDROID_URL.endswith("/SearchMob")  # the sibling repo, not the desktop one

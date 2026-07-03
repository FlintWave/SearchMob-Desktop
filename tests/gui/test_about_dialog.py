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


def test_about_opens_wide_enough_for_its_content(qapp: object) -> None:
    """The dialog derives its opening width from the content, so no horizontal scrollbar.

    A fixed opening width regressed whenever the app font size or the active language made the
    widest row (the buttons row, the unwrapped footer lines) wider than it: the scroll area then
    showed a horizontal scrollbar over what is a short static page. Guard the derivation at a
    larger-than-default font, mocking a roomy screen so the small offscreen test display's clamp
    does not mask the width calculation.
    """
    from unittest.mock import patch

    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication, QScrollArea

    font = QApplication.font()
    original_size = font.pointSize()
    font.setPointSize(20)
    QApplication.setFont(font)
    try:
        screen_type = type(QApplication.primaryScreen())
        with patch.object(screen_type, "availableGeometry", lambda self: QRect(0, 0, 1920, 1052)):
            dialog = AboutDialog()
            dialog.show()
            QApplication.processEvents()
            scroll = dialog.findChild(QScrollArea)
            assert scroll is not None
            assert scroll.viewport().width() >= scroll.widget().minimumSizeHint().width()
            assert not scroll.horizontalScrollBar().isVisible()
            dialog.close()
    finally:
        font.setPointSize(original_size)
        QApplication.setFont(font)

"""BrowserSetupDialog URL building: the token must appear in network-mode templates only.

Drives the pure `_setup_urls` helper plus a smoke check that the dialog renders the token-bearing
URLs into its cards when a token is supplied. Offscreen Qt only; nothing touches disk or network.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMessageBox

from searchmob_desktop.gui.browser_setup_dialog import BrowserSetupDialog, _setup_urls


def test_setup_urls_appends_token_to_search_and_suggest() -> None:
    visit, search, suggest = _setup_urls("192.168.1.50", 8787, token="tok-xyz")
    # The visit URL (the open `/` route) stays token-free.
    assert visit == "http://192.168.1.50:8787/"
    assert search == "http://192.168.1.50:8787/search?q={searchTerms}&token=tok-xyz"
    assert suggest == "http://192.168.1.50:8787/suggest?q={searchTerms}&token=tok-xyz"


def test_setup_urls_omits_token_when_loopback() -> None:
    for token in (None, ""):
        visit, search, suggest = _setup_urls("127.0.0.1", 8787, token=token)
        assert "token=" not in visit
        assert "token=" not in search
        assert "token=" not in suggest


def _all_label_text(dialog: BrowserSetupDialog) -> str:
    return "\n".join(label.text() for label in dialog.findChildren(QLabel))


def test_dialog_renders_token_url_in_network_mode(qapp: object) -> None:
    dialog = BrowserSetupDialog(host="192.168.1.50", port=8787, token="tok-xyz")
    text = _all_label_text(dialog)
    assert "/search?q={searchTerms}&token=tok-xyz" in text
    assert "/suggest?q={searchTerms}&token=tok-xyz" in text


def test_dialog_loopback_has_no_token(qapp: object) -> None:
    dialog = BrowserSetupDialog(host="127.0.0.1", port=8787)
    text = _all_label_text(dialog)
    assert "token=" not in text


def test_copy_flashes_inline_instead_of_modal(
    qapp: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying confirms with a green outline + fading checkmark, never a modal dialog."""
    modal: dict[str, bool] = {}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: modal.setdefault("shown", True))

    dialog = BrowserSetupDialog(host="127.0.0.1", port=8787)
    url_fields = [w for w in dialog.findChildren(QLabel) if w.property("role") == "url"]
    assert url_fields, "expected at least one URL field"
    field = url_fields[0]

    dialog._copy("http://127.0.0.1:8787/", field)

    # The value reached the clipboard.
    clipboard = QGuiApplication.clipboard()
    assert clipboard is not None
    assert clipboard.text() == "http://127.0.0.1:8787/"
    # No modal dialog was shown.
    assert "shown" not in modal
    # A checkmark badge was floated over the field, and the field got the green outline.
    badges = [w for w in field.findChildren(QLabel) if w.text() == "✓"]
    assert badges, "expected a checkmark badge over the field"
    assert dialog._COPIED_GREEN in field.styleSheet()

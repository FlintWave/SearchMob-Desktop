"""Result-ranking Settings tab: lenses, domain rules, goggles, persistence + rulesChanged."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.engines.rank import DEFAULT_SAMPLE_LENSES, RankingRules, RankRule
from searchmob_desktop.gui import settings_dialog as sd
from searchmob_desktop.prefs import JsonPreferencesStore


@pytest.fixture
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> dict[str, RankingRules]:
    """Replace the vault-backed ranking store with an in-memory holder for the dialog module."""
    holder: dict[str, RankingRules] = {"rules": RankingRules()}
    monkeypatch.setattr(sd, "load_ranking_rules", lambda: holder["rules"])

    def _save(rules: RankingRules) -> bool:
        holder["rules"] = rules
        return True

    monkeypatch.setattr(sd, "save_ranking_rules", _save)
    return holder


def _dialog(tmp_path, fake_vault):  # type: ignore[no-untyped-def]
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    return sd.SettingsDialog(prefs_store=store)


def test_select_active_sample_lens(qapp, tmp_path, fake_vault) -> None:  # type: ignore[no-untyped-def]
    # The sample scopes are present by default (seeded by the ranking store); the dialog lists them
    # and selecting one activates it, clearing it on "No scope".
    fake_vault["rules"] = RankingRules(lenses=DEFAULT_SAMPLE_LENSES)
    dialog = _dialog(tmp_path, fake_vault)
    assert dialog._lens_combo.count() == len(DEFAULT_SAMPLE_LENSES) + 1  # +1 for "No scope"

    dialog._lens_combo.setCurrentIndex(1)
    assert fake_vault["rules"].active_lens == dialog._lens_combo.itemText(1)
    dialog._lens_combo.setCurrentIndex(0)
    assert fake_vault["rules"].active_lens is None


def test_remove_and_clear_domain_rules(qapp, tmp_path, fake_vault) -> None:  # type: ignore[no-untyped-def]
    fake_vault["rules"] = (
        RankingRules()
        .with_domain_rule("a.example", RankRule.BLOCK)
        .with_domain_rule("b.example", RankRule.PIN)
    )
    dialog = _dialog(tmp_path, fake_vault)
    assert dialog._rules_list.count() == 2

    dialog._rules_list.setCurrentRow(0)
    dialog._on_remove_domain_rule()
    assert len(fake_vault["rules"].domain_rules) == 1

    dialog._on_clear_domain_rules()
    assert fake_vault["rules"].domain_rules == {}


def test_import_pasted_goggles(qapp, tmp_path, fake_vault, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dialog = _dialog(tmp_path, fake_vault)
    dialog._goggle_text.setPlainText("$discard,site=spam.example\n$boost,site=dev.to")
    dialog._on_import_goggles_pasted()
    sites = {g.site for g in fake_vault["rules"].goggles}
    assert sites == {"spam.example", "dev.to"}


def test_slop_combo_defaults_to_downrank_and_persists(qapp, tmp_path, fake_vault) -> None:  # type: ignore[no-untyped-def]
    store = JsonPreferencesStore(path=tmp_path / "prefs.json")
    dialog = sd.SettingsDialog(prefs_store=store)
    # Default pref is "downrank" so the combo starts there.
    assert dialog._slop_combo.currentData() == "downrank"

    changed: list[int] = []
    dialog.rulesChanged.connect(lambda: changed.append(1))

    dialog._slop_combo.setCurrentIndex(dialog._slop_combo.findData("hide"))
    assert changed  # rulesChanged fired so the main window re-ranks live
    assert store.load().ai_slop_mode == "hide"

    dialog._slop_combo.setCurrentIndex(dialog._slop_combo.findData("off"))
    assert store.load().ai_slop_mode == "off"

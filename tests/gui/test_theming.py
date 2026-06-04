"""Tests for the named-theme library, the two-slot resolver, font scaling, and a11y contrast.

These are pure helpers (no `QApplication` / display needed) but live behind a PySide6 import guard
because the theme module is under `gui/`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


from searchmob_desktop.gui.theme import (
    DARK,
    DARK_THEME_IDS,
    DEFAULT_DARK_ID,
    DEFAULT_FONT_PT,
    DEFAULT_LIGHT_ID,
    LIGHT,
    LIGHT_THEME_IDS,
    MAX_FONT_PT,
    MIN_FONT_PT,
    THEMES,
    build_qss,
    clamp_font_pt,
    contrast_ratio,
    resolve_active_theme,
)

_SLATE = {
    "searchmob-light",
    "searchmob-dark",
    "github-light",
    "one-dark",
    "dracula",
    "tokyo-night",
    "catppuccin-mocha",
    "catppuccin-latte",
    "gruvbox",
    "nord",
    "rose-pine-dawn",
    "obsidian-slate",
    "paper-white",
}


def test_library_contains_the_full_slate() -> None:
    assert set(THEMES) == _SLATE
    assert len(THEMES) == 13


def test_light_and_dark_id_lists_partition_by_mode() -> None:
    assert set(LIGHT_THEME_IDS) | set(DARK_THEME_IDS) == set(THEMES)
    assert set(LIGHT_THEME_IDS) & set(DARK_THEME_IDS) == set()
    assert all(THEMES[i].mode == LIGHT for i in LIGHT_THEME_IDS)
    assert all(THEMES[i].mode == DARK for i in DARK_THEME_IDS)
    # The accessibility pair: one light, one dark.
    assert "paper-white" in LIGHT_THEME_IDS
    assert "obsidian-slate" in DARK_THEME_IDS


def test_defaults_keep_the_original_searchmob_look() -> None:
    assert DEFAULT_LIGHT_ID == "searchmob-light"
    assert DEFAULT_DARK_ID == "searchmob-dark"
    assert THEMES[DEFAULT_LIGHT_ID].mode == LIGHT
    assert THEMES[DEFAULT_DARK_ID].mode == DARK


def test_resolve_active_theme_truth_table() -> None:
    # Light mode -> light slot, regardless of OS scheme.
    assert resolve_active_theme("light", "github-light", "one-dark", False).id == "github-light"
    assert resolve_active_theme("light", "github-light", "one-dark", True).id == "github-light"
    # Dark mode -> dark slot.
    assert resolve_active_theme("dark", "github-light", "one-dark", False).id == "one-dark"
    # System -> follows the OS scheme.
    assert resolve_active_theme("system", "github-light", "one-dark", True).id == "one-dark"
    assert resolve_active_theme("system", "github-light", "one-dark", False).id == "github-light"
    # Absent/unknown mode is treated as system.
    assert resolve_active_theme(None, "github-light", "one-dark", True).id == "one-dark"


def test_resolve_active_theme_falls_back_on_bad_slot_ids() -> None:
    # Unknown id -> the slot default.
    assert resolve_active_theme("light", "nope", "one-dark", False).id == DEFAULT_LIGHT_ID
    assert resolve_active_theme("dark", "github-light", "nope", False).id == DEFAULT_DARK_ID
    # A dark theme placed in the light slot is rejected (mode mismatch) -> light default.
    assert resolve_active_theme("light", "one-dark", "one-dark", False).id == DEFAULT_LIGHT_ID


def test_contrast_ratio_matches_known_extremes() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)
    assert contrast_ratio("#ffffff", "#ffffff") == pytest.approx(1.0, abs=0.01)


def test_all_themes_meet_aa_body_contrast() -> None:
    # Every theme's primary text must clear WCAG AA (4.5:1) against its background.
    for theme in THEMES.values():
        ratio = contrast_ratio(theme.palette.text, theme.palette.bg)
        assert ratio >= 4.5, f"{theme.id} text-on-bg only {ratio:.2f}:1"


def test_accessibility_themes_meet_aaa_contrast() -> None:
    # The two accessibility themes target AAA (7:1) for body text and AA (4.5:1) for links.
    for theme_id in ("paper-white", "obsidian-slate"):
        p = THEMES[theme_id].palette
        assert contrast_ratio(p.text, p.bg) >= 7.0
        assert contrast_ratio(p.accent, p.bg) >= 4.5


def test_build_qss_uses_the_palette_and_scales_with_font() -> None:
    theme = THEMES["one-dark"]
    qss = build_qss(theme.palette, DEFAULT_FONT_PT)
    assert theme.palette.bg in qss
    # 12pt resolves to the standard 16px web base; a larger size enlarges it.
    assert "font-size: 16px" in qss
    assert "font-size: 21px" in build_qss(theme.palette, 16)


def test_clamp_font_pt_bounds_and_rejects_junk() -> None:
    assert clamp_font_pt(12) == 12
    assert clamp_font_pt(2) == MIN_FONT_PT
    assert clamp_font_pt(99) == MAX_FONT_PT
    assert clamp_font_pt("nope") == DEFAULT_FONT_PT
    assert clamp_font_pt(None) == DEFAULT_FONT_PT
    # bool is an int subclass but is not a meaningful font size; treat as junk.
    assert clamp_font_pt(True) == DEFAULT_FONT_PT

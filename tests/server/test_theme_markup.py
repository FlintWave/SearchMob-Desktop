"""Served-page theming: the generated per-theme CSS variable blocks, the two-slot + font init JS,
and the Appearance settings picker. The served themes are browser-local (localStorage), so this is
all markup assertions; nothing touches the server's stored state.
"""

from __future__ import annotations

from searchmob_desktop.engines.rank import RankingRules
from searchmob_desktop.gui.theme import DEFAULT_DARK_ID, DEFAULT_LIGHT_ID, LIGHT, THEMES
from searchmob_desktop.prefs import UserPreferences
from searchmob_desktop.server.templates import (
    render_home_page,
    render_results_page,
    render_settings_page,
)


def _is_safe(_url: str) -> bool:
    return True


def test_every_theme_emits_a_data_theme_block() -> None:
    html = render_home_page()
    # Every named theme in the registry gets its own override block, so the picker can select it.
    for theme_id in THEMES:
        assert f'[data-theme="{theme_id}"]{{' in html
    # The two defaults drive :root and the dark media query.
    assert ":root{" in html
    assert "@media (prefers-color-scheme:dark){:root{" in html


def test_default_theme_palettes_match_the_gui() -> None:
    html = render_home_page()
    light = THEMES[DEFAULT_LIGHT_ID].palette
    dark = THEMES[DEFAULT_DARK_ID].palette
    # The served :root vars use the GUI light palette; the dark block uses the GUI dark palette.
    assert f"--bg:{light.bg};" in html
    assert f"--accent:{light.accent};" in html
    assert f"--bg:{dark.bg};" in html
    assert f"--accent:{dark.accent};" in html


def test_data_theme_block_maps_palette_fields() -> None:
    html = render_home_page()
    theme = THEMES["dracula"]
    p = theme.palette
    block = '[data-theme="dracula"]{'
    start = html.index(block)
    chunk = html[start : html.index("}", start)]
    assert f"--bg:{p.bg};" in chunk
    assert f"--card:{p.surface};" in chunk  # --card maps to surface, not the palette's card
    assert f"--chip-bg:{p.card_hover};" in chunk
    assert f"--url:{p.url};" in chunk
    assert f"--topbar:{p.bg}ee;" in chunk  # 8-digit hex with alpha


def test_font_root_rule_present_and_content_scales_in_rem() -> None:
    html = render_home_page()
    assert "html{font-size:12pt}" in html
    # Key content sizes are rem so they scale with the root font size.
    assert ".result .title{display:block;font-size:1.25rem;" in render_results_page(
        "hi", [], _is_safe
    )
    assert "font-size:1rem;padding:13px 18px}" in html  # the search input
    assert ".home .brand{font-size:3rem;" in html


def test_init_js_references_the_two_slots_and_font() -> None:
    html = render_home_page()
    assert "sm-theme" in html
    assert "sm-light-theme" in html
    assert "sm-dark-theme" in html
    assert "sm-font" in html
    # Defaults mirror the GUI two-slot defaults.
    assert DEFAULT_LIGHT_ID in html
    assert DEFAULT_DARK_ID in html


def test_results_page_also_carries_the_theme_blocks() -> None:
    html = render_results_page("hi", [], _is_safe)
    for theme_id in THEMES:
        assert f'[data-theme="{theme_id}"]{{' in html


def _settings_html() -> str:
    return render_settings_page(UserPreferences(), RankingRules())


def test_settings_page_has_the_appearance_picker() -> None:
    html = _settings_html()
    assert "<h2>Appearance</h2>" in html
    # The three selects, by id.
    assert 'id="sm-mode"' in html
    assert 'id="sm-light-theme"' in html
    assert 'id="sm-dark-theme"' in html
    # Mode options.
    assert ">Follow system<" in html


def test_settings_light_and_dark_selects_list_their_themes() -> None:
    html = _settings_html()
    light_start = html.index('id="sm-light-theme"')
    light_chunk = html[light_start : html.index("</select>", light_start)]
    dark_start = html.index('id="sm-dark-theme"')
    dark_chunk = html[dark_start : html.index("</select>", dark_start)]
    for theme in THEMES.values():
        if theme.mode == LIGHT:
            assert f'value="{theme.id}"' in light_chunk
            assert f'value="{theme.id}"' not in dark_chunk
        else:
            assert f'value="{theme.id}"' in dark_chunk
            assert f'value="{theme.id}"' not in light_chunk


def test_settings_page_has_the_text_size_stepper() -> None:
    html = _settings_html()
    assert 'id="sm-font-dec"' in html
    assert 'id="sm-font-inc"' in html
    assert ">A-<" in html
    assert ">A+<" in html
    assert 'id="sm-font-val"' in html


def test_settings_controls_js_is_emitted_only_on_settings() -> None:
    settings = _settings_html()
    home = render_home_page()
    # The picker-wiring script lives on settings; the resolve helper names appear, plus the stepper.
    assert "sm-font-inc" in settings
    assert "sm-font-inc" not in home

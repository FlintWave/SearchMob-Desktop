# Tasks: theming (desktop)

## Theme registry + model

- [ ] `gui/theme.py`: replace the two `Palette` constants with a `THEMES` registry of eleven themes
      (id, display name, mode, `Palette`, optional credit). Copy the locked hex palettes verbatim.
- [ ] `gui/theme.py`: add `resolve_active_theme(mode, light_id, dark_id, os_is_dark) -> Theme` and make
      `apply_theme` take the resolved theme; cache QSS per theme id.
- [ ] `prefs.py` / `UserPreferences`: add `light_theme` (default `github-light`), `dark_theme`
      (default `one-dark`), `font_point_size` (int, default 12, bounds 8-24). Keep `theme` as the mode.

## Font size

- [ ] `gui/theme.py`: set the QApplication base font to `font_point_size` pt and derive QSS font sizes
      relative to that base so result text scales with interface text.

## GUI controls

- [ ] `gui/settings_dialog.py` Appearance tab: keep the light/dark/system radios; add a "Light theme"
      dropdown, a "Dark theme" dropdown (each listing only that mode's themes), and A-/A+ font-size
      step buttons (2pt steps, 12pt default, bounded) with the current size shown. Persist + re-apply
      on change.
- [ ] `gui/main_window.py`: quick toggle resolves through the two-slot model; `_update_theme_button`
      still reflects the current mode.

## Served page

- [ ] `server/templates.py`: emit one `[data-theme="<id>"]` block per theme; update `_THEME_INIT_JS`
      and `_THEME_TOGGLE_JS` to use `sm-theme` (mode) + `sm-light-theme` + `sm-dark-theme` and resolve
      slot -> id pre-paint; add a font-scale `data-font` attribute + `sm-font` restore.
- [ ] `server/templates.py`: convert component px font-sizes to `rem` so font scale cascades.
- [ ] `server/app.py` + `render_settings_page`: expose the theme picker + font-size control on
      `/settings` (and a compact theme control in the top bar).

## Credits

- [ ] Add/extend a `CREDITS` (or third-party licenses) notice listing the nine reused palettes and
      their upstream licenses; the two accessibility themes are noted as original.

## Verify + ship

- [ ] ruff (check + format) + mypy --strict + pytest green (GUI tests `QT_QPA_PLATFORM=offscreen`).
- [ ] New tests: `resolve_active_theme` truth table; applied QSS contains the selected theme's bg hex;
      font scale changes the base font size; each served theme id emits its `[data-theme]` block;
      a11y themes meet the AA/AAA contrast threshold; GUI/served theme-id lists match.
- [ ] Manual: cycle all 11 themes in the GUI and on the served page; confirm every element recolours,
      the quick toggle swaps slots, font sizes reflow cleanly, and the a11y themes read as high
      contrast. Screenshot-review per the release-verification procedure.
- [ ] Ship as part of the RC feature pile (theming + i18n + engine-status + media-intent); one `-rc`
      tag for the pile, not a per-feature GA. Add a `## [Unreleased]` CHANGELOG entry.

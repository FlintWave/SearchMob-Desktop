# Design: theming

## Theme model (two-slot, layered on the existing mode)

The existing model is a single `theme` mode: `light` / `dark` / `system`. Rather than replace it, this
change layers named themes on top:

- Keep `themeMode` = `light` | `dark` | `system` (the quick toggle, unchanged semantics).
- Add `light_theme` = id of the active light theme (default `github-light`).
- Add `dark_theme` = id of the active dark theme (default `one-dark`).
- Resolved theme: `system` -> (OS dark ? `dark_theme` : `light_theme`); `light` -> `light_theme`;
  `dark` -> `dark_theme`.

The quick light/dark toggle therefore keeps working with zero behaviour change; it now swaps between
the user's chosen light and dark themes instead of two hard-coded palettes. The full picker simply
chooses which named theme occupies each slot. Picking a theme sets its slot AND switches `themeMode`
to that slot's mode so the change is visible immediately. "Follow system" still resolves by OS
appearance. This reuses every surface's existing light/dark/system plumbing and persistence and keeps
the existing tests meaningful.

## The slate (ids, mode, palette)

Nine themed + two accessibility = eleven. Light slot candidates: `github-light`, `catppuccin-latte`,
`rose-pine-dawn`, `paper-white`. Dark slot candidates: `one-dark`, `dracula`, `tokyo-night`,
`catppuccin-mocha`, `gruvbox`, `nord`, `obsidian-slate`. Each theme defines six roles (background,
surface, primary text, muted text, accent/link, border); the GUI maps these onto the existing
`Palette` fields and the served pages onto the existing CSS custom properties. Exact hex values are in
`~/.claude/plans/searchmob-theming-research.md` (the locked slate) and are copied verbatim into the
registries. `obsidian-slate` and `paper-white` are custom AAA palettes (no third-party attribution
needed); the other nine reuse upstream open-source palettes and are credited.

## Per-surface implementation

### Desktop GUI (`gui/theme.py`, `gui/settings_dialog.py`, `gui/main_window.py`)
- Replace the two `Palette` constants with a `THEMES: dict[str, Theme]` registry, where `Theme` carries
  the id, display name, `mode` (light/dark), the `Palette`, and an optional `credit` (name + license).
  `build_qss(palette)` is unchanged; pre-compile QSS lazily per theme (cache by id).
- `resolve_theme()` becomes `resolve_active_theme(mode, light_id, dark_id, os_is_dark) -> Theme`.
  `apply_theme()` takes the resolved `Theme` and sets `app.setStyleSheet(qss_for(theme))`.
- Font size: a `font_point_size` int (default 12, range 8-24, 2pt steps). Apply by setting the
  `QApplication` base font point size to `font_point_size` before/with `setStyleSheet`, and have
  `build_qss` derive its font sizes relative to that base (em/relative, not fixed px) so result text
  scales with it. The control is two step buttons (A- / A+) that adjust by 2pt within the bounds; the
  default leans comfortably large (12pt) rather than cramped.
- Appearance tab (`_build_appearance_tab`): keep the light/dark/system radios as the mode control; add
  a "Light theme" dropdown (light-slot candidates), a "Dark theme" dropdown (dark-slot candidates), and
  A-/A+ font-size step buttons. Each change saves the pref and re-applies. The main-window quick toggle button
  is unchanged; `_update_theme_button` still reflects the current mode.

### Desktop served page (`server/templates.py`, `server/app.py`)
- The CSS is already fully variable-driven with `[data-theme="light"]` / `[data-theme="dark"]` blocks.
  Generate one `[data-theme="<id>"]` block per theme from the shared registry (a single source of
  palette truth shared with the GUI where practical, or a mirrored table).
- `_THEME_INIT_JS` / `_THEME_TOGGLE_JS`: store `sm-light-theme`, `sm-dark-theme`, and the existing
  `sm-theme` (mode) in localStorage. Init resolves mode -> slot -> id and sets `data-theme="<id>"` on
  `<html>` pre-paint. The quick toggle flips mode and applies the matching slot's id. A picker control
  on `/settings` (and a compact control in the top bar) sets the slot ids.
- Font size: set the root font size directly in points (`html{font-size:<n>pt}`; CSS supports `pt`
  and 12pt resolves to the standard ~16px web base), and convert the handful of px font-sizes in
  component CSS to `rem` so the root size cascades. Persist the pt int as `sm-font` in localStorage;
  restore pre-paint alongside the theme. The A-/A+ controls step the pt value by 2 within the bounds.

### Android (mirror; see the Android repo's add-theming change)
- Compose: a `Theme` registry feeding Material3 `ColorScheme`s (map the six roles onto the scheme
  slots), `ThemeMode` unchanged, add `lightThemeId`/`darkThemeId`/`fontPointSize` to `UserPreferences`
  (DataStore). Font size via a scaled `Typography` derived from `fontPointSize / 12` (12pt base) so
  Android's sp-based text honours the same control. `SettingsScreen` gains the two dropdowns + A-/A+
  font-size step buttons next to the existing mode radios.
- Served page (`SearchServer.kt`): identical CSS-variable + localStorage approach as desktop served.

## Persistence / privacy

Theme mode, the two slot ids, and font scale are local UI preferences (desktop JSON prefs / Android
DataStore / served-page localStorage), never transmitted, never search data. Consistent with
store-nothing-by-default. No new network calls or dependencies.

## Credits

The nine reused palettes (One Dark, GitHub, Dracula, Tokyo Night, Catppuccin Mocha/Latte, Gruvbox,
Nord, Rose Pine) are credited with their upstream licenses in a `CREDITS`/third-party notice. The two
accessibility palettes are original to SearchMob.

## Testing

- GUI: `resolve_active_theme` truth table (mode x slot x os) returns the right theme; applying a theme
  yields QSS containing that theme's background hex; font scale changes the base font size; the
  Appearance tab dropdowns persist and re-apply (offscreen Qt).
- Served: each theme id emits a matching `[data-theme="<id>"]` block; the init/toggle JS is present;
  the font-scale attribute and rem conversion render; `/settings` exposes the picker.
- Accessibility: a unit check that the two a11y themes' primary-text-on-background contrast ratio
  meets the AA/AAA threshold (compute relative luminance from the hex values).
- Parity: the theme id list is identical between GUI and served registries.

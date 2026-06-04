## Why

The app ships exactly two looks: a single light palette and a single dark palette, chosen by a
light/dark/system control. Users who spend hours in a search tool want their own look, and some need
a high-contrast or larger-text option to read comfortably. Today there is no way to pick a different
palette, size the text, or get a vetted accessibility theme. This adds a real theme library, a picker,
and two quality-of-life controls (font size and an accessibility high-contrast option) without
disturbing the store-nothing, owner-first posture.

## What Changes

- Add a library of named themes (a slate of nine plus two accessibility themes), each a full palette
  applied through the existing styling layer. The two accessibility themes are verified to meet WCAG
  AA/AAA contrast and serve as the app's high-contrast option.
- Keep the existing quick light/dark/system toggle unchanged, and add a full theme picker that chooses
  which named theme fills the light slot and which fills the dark slot (a "two-slot" model layered on
  the existing `themeMode`). The quick toggle keeps swapping between those two slots.
- Add a font-size control: a comfortable 12pt base with step buttons that raise or lower the size by
  2pt (bounded), resizing interface and result text together. The choice is remembered between uses.
- Apply all of the above to every surface: the desktop GUI, the served page, and (mirrored) the
  Android app and its served page, so the look is consistent everywhere.
- Reused third-party palettes are credited with their upstream licenses in a credits notice.

## Capabilities

### New Capabilities
- `theming`: a library of named themes plus font-size and accessibility controls, selectable per
  light/dark slot, applied consistently across the GUI, the served page, and the Android surfaces, and
  persisted as a local UI preference.

### Modified Capabilities
<!-- None in contract. The existing light/dark/system control keeps its meaning; the named-theme slot
selection and font size are additive preferences. -->

## Non-goals

- User-authored or importable custom themes: the library is a fixed, curated slate this change.
- Per-element or syntax-style theming: SearchMob has no code editor; themes color the app chrome and
  result list, not token-level syntax.
- Computing a high-contrast variant of every theme: high contrast is delivered by the two dedicated
  accessibility themes, not a per-theme contrast booster.
- Syncing the chosen theme between the desktop app and a LAN browser client: each surface persists its
  own local preference (the served page in the browser, the app in its prefs store).

## Impact

- Modified: `gui/theme.py` (a registry of `Palette`s instead of two constants; font-scale applied to
  the base font), `gui/settings_dialog.py` (Appearance tab gains a theme picker + font-size control),
  `gui/main_window.py` (quick toggle resolves through the two-slot model), `server/templates.py` (a
  `[data-theme="<id>"]` block per theme + the picker control + font-scale), `server/app.py` (serve the
  picker on `/settings`), `prefs.py`/`UserPreferences` (add `light_theme`, `dark_theme`, `font_scale`).
  Mirrored on Android (`ui/theme/`, `SettingsScreen`, `SearchServer.kt`). A credits/licenses notice
  lists each reused palette.
- No new dependencies, no new outbound calls, no telemetry. Theme/font choices are local UI prefs
  (not search data), consistent with store-nothing-by-default. Owner/LAN gating unchanged.

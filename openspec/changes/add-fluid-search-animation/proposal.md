## Why

The search transition in the Desktop app feels abrupt: pressing Enter replaces the status line with
"Searching ..." and then snap-loads results into the list. The served web pages have the same gap:
the search button submits, the page goes blank, and the results appear in a hard cut. There is no
visual continuity between typing and receiving results, and no sense of progress while the
metasearch fan-out runs. Adding a fluid-fill animation inside the search field itself turns the
dead time into a polished, branded moment. This directly serves **parity with the Android app**
(where the same layered-wave animation is being added as issue #117) and the **customizable**
goal: users who keep SearchMob open all day should see a reward on each interaction, not a blank
line.

The animation respects all Desktop themes (it derives its palette from the active theme's
accent/surface/border tokens) and adds no telemetry, network calls, or new permissions.

## What Changes

### 1. Fluid-fill progress indicator in the search field (Qt GUI)

When the user presses Enter (or clicks Search), a layered-wave animation plays inside the
`QLineEdit` search field:

- A `QWidget` overlay positioned on top of the search input draws three layered sine waves at
  different frequencies and amplitudes that fill from left to right, acting as a progress bar
  (time-based with an ease curve, since fan-out completion is not granular enough for true
  determinate progress).
- **Style: Layered Waves (Style B).** Three sine layers at different frequencies, slightly offset,
  with semi-transparent blending. Matches the Android implementation exactly.
- **Performance:** the sine math is trivial (three `sin()` calls per x-pixel per frame). The
  overlay paints via `QPainter` with gradient fills, no pixel-level operations, no allocations in
  the paint loop. Uses `QTimer` at ~60 fps (16 ms interval). The animation runs only during the
  ~1-3s search window and stops immediately on results.
- Colors derive from the active theme's `accent` (fluid body), `surface` (gradient top), and a
  computed foam color (white at reduced opacity). Works across all Desktop themes.
- When results arrive, the bar quickly fills any remaining width (fast ease-to-100%), then the
  results list animates into view with a slide-up effect using `QPropertyAnimation` on the results
  widget's geometry or a `QGraphicsOpacityEffect` fade. A 2px accent top border on the results
  view fades from full opacity to zero over the slide duration.

### 2. Fluid-fill progress indicator on the served page (web UI)

The same layered-wave visual on the Starlette-served search page:

- A `<canvas>` element positioned inside the search `<input>` wrapper (the `.searchbox`).
- JavaScript drives three layered sine waves, reading CSS custom properties (`--accent`,
  `--bg`, etc.) for theme-aware colors.
- **Performance:** uses `requestAnimationFrame` (not `setInterval`), cancels on results, allocates
  nothing in the draw loop. The canvas is sized to the input field (small).
- On form submit, the canvas animates; on results load, it fills and the results container slides
  up with a CSS transition. The results container has a clear top border that fades from full
  opacity to transparent over the 400ms slide-up transition.
- No external JS dependencies; the simulation is a self-contained ~60-line module inlined in the
  served page (added to `templates.py`).

### 3. Accessibility and reduced motion

- When the Qt "Remove animations" accessibility setting is active (`QApplication.isAnimationEnabled()
  == False`), or on the web when `prefers-reduced-motion` is active, fall back to a simple
  left-to-right color wipe (no wave physics) at the same progress rate.
- The fluid overlay does not obscure the query text (text z-order stays above the canvas; the
  fluid is semi-transparent).
- Screen readers see no change: the existing status label / `aria-busy` attribute is retained.

## Capabilities

### New Capabilities
- `fluid-search-animation`: a theme-aware 1D fluid-fill progress animation inside the search
  field, with a slide-up results transition, on both the Qt GUI and the served web page.

### Modified Capabilities
- `search-loading`: the existing "Searching ..." status text is retained as the accessible
  announcement, but the visible loading experience is now the in-field fluid animation.

## Non-goals

- Full 2D Navier-Stokes, SPH particles, or heightfield physics: unnecessarily heavy. Layered sine
  waves are visually clean and lightweight.
- User-configurable animation style or speed: the animation is a fixed part of the brand.
- Animating anything outside the search field (no full-window fluid, no splash).
- Progress tied to individual engine responses: the fan-out completes too fast and unevenly for
  per-engine ticks to look smooth. The progress curve is time-based with a fast finish on
  completion.
- Lottie or GIF assets: the simulation is code-driven and theme-aware; a canned asset cannot adapt
  to multiple palettes.

## Impact

- **Modified files (GUI):**
  - `gui/main_window.py`: wire the wave overlay widget on submit and hide it on results; add
    slide-up transition for the results view.

- **New files (GUI):**
  - `gui/wave_overlay.py`: the `QWidget` overlay that draws three sine-wave layers via `QPainter`.
    Contains the wave math (pure functions, unit-testable) and the paint/timer loop.

- **Modified files (web):**
  - `server/templates.py`: inline the JS fluid module in the served page `<script>`, wire it to
    the search form's submit event, and add the slide-up CSS transition for the results container.

- **New files (web):** none (JS is inlined in the served HTML template).

- **No new dependencies.** The simulation uses `math` (Python) and vanilla JS `Math` / Canvas 2D.
- **No new permissions, no network calls, no telemetry.**
- **Tests:** unit tests for the wave math functions (deterministic step), GUI test asserting the
  overlay appears on submit and disappears on results.

"""Theme for the PySide6 shell: a small, COSMIC-leaning design system.

This defines a flat, rounded, accent-driven look with consistent spacing, card-style result rows,
and a library of named themes. Each theme is a full `Palette`; the user picks which named theme
fills the light slot and which fills the dark slot, and the existing light/dark/system mode chooses
between those two slots (the "two-slot" model). `SYSTEM` follows the OS scheme via
`QApplication.styleHints().colorScheme()`. A font-size preference (in points) scales the whole UI.

The pure helpers (`resolve_theme`, `resolve_active_theme`, `theme_stylesheet`, `build_qss`, the
color math) stay import-safe (no PySide6 import) so headless tests can exercise them. `apply_theme`
and `effective_palette` touch the running `QApplication` and resolve `SYSTEM` to a concrete theme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication

LIGHT = "light"
DARK = "dark"
SYSTEM = "system"

_VALID = frozenset({LIGHT, DARK, SYSTEM})

# Font size, in points. The base leans comfortably large; the A-/A+ controls step by 2pt.
DEFAULT_FONT_PT = 12
MIN_FONT_PT = 8
MAX_FONT_PT = 24
FONT_STEP_PT = 2


@dataclass(frozen=True)
class Palette:
    """The colors the whole UI is built from. Drives both the QSS and the result delegate."""

    bg: str  # window background
    surface: str  # inputs, toolbar buttons, status bar
    card: str  # result row card
    card_hover: str  # result row hover
    border: str  # hairline borders
    text: str  # primary text
    muted: str  # secondary text (snippet, hints, URL fallback)
    accent: str  # primary action + focus + selection
    accent_hover: str
    on_accent: str  # text on an accent fill
    url: str  # result URL color
    engine: str  # result engine badge color
    danger_bg: str
    danger_border: str
    danger_text: str


# --- Color math (pure; reused by the theme factory and the contrast test) --------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    h = value.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02x}{max(0, min(255, g)):02x}{max(0, min(255, b)):02x}"


def _mix(a: str, b: str, t: float) -> str:
    """Blend `a` toward `b` by fraction `t` (0 keeps `a`, 1 returns `b`)."""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    return _rgb_to_hex(
        round(ar + (br - ar) * t), round(ag + (bg - ag) * t), round(ab + (bb - ab) * t)
    )


def _linearize(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(value: str) -> float:
    r, g, b = _hex_to_rgb(value)
    return 0.2126 * _linearize(r) + 0.7152 * _linearize(g) + 0.0722 * _linearize(b)


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast ratio between two hex colors (>= 1.0)."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _on_color(bg: str) -> str:
    """Pick near-black or white for the most readable text on an accent fill."""
    near_black = "#0b0b0c"
    if contrast_ratio(bg, near_black) >= contrast_ratio(bg, "#ffffff"):
        return near_black
    return "#ffffff"


def _from_roles(
    mode: str,
    *,
    bg: str,
    surface: str,
    text: str,
    muted: str,
    accent: str,
    border: str,
    on_accent: str | None = None,
) -> Palette:
    """Build a full `Palette` from the six theme roles, deriving the rest per light/dark mode."""
    on = on_accent if on_accent is not None else _on_color(accent)
    if mode == DARK:
        card_hover = _mix(surface, "#ffffff", 0.07)
        accent_hover = _mix(accent, "#ffffff", 0.14)
        engine = "#5fcf8f"
        danger_bg, danger_border, danger_text = "#3a1d1f", "#6e3236", "#ff9ea2"
    else:
        card_hover = _mix(surface, accent, 0.10)
        accent_hover = _mix(accent, "#000000", 0.12)
        engine = "#1f8f4e"
        danger_bg, danger_border, danger_text = "#fdecec", "#f3b9b9", "#a32020"
    return Palette(
        bg=bg,
        surface=surface,
        card=surface,
        card_hover=card_hover,
        border=border,
        text=text,
        muted=muted,
        accent=accent,
        accent_hover=accent_hover,
        on_accent=on,
        url=accent,
        engine=engine,
        danger_bg=danger_bg,
        danger_border=danger_border,
        danger_text=danger_text,
    )


# COSMIC-leaning SearchMob palettes (the defaults): flat surfaces, one blue accent, generous
# contrast. Kept as full palettes so the existing look is unchanged for users who never switch.
DARK_PALETTE = Palette(
    bg="#161619",
    surface="#212127",
    card="#26262d",
    card_hover="#2f2f38",
    border="#34343d",
    text="#e9e9ee",
    muted="#9a9aa4",
    accent="#5b7cfa",
    accent_hover="#6d8bff",
    on_accent="#ffffff",
    url="#8fb0ff",
    engine="#5fcf8f",
    danger_bg="#3a1d1f",
    danger_border="#6e3236",
    danger_text="#ff9ea2",
)

LIGHT_PALETTE = Palette(
    bg="#f3f4f7",
    surface="#ffffff",
    card="#ffffff",
    card_hover="#eef1fb",
    border="#e1e2e9",
    text="#1a1a1f",
    muted="#6a6a75",
    accent="#3f6fff",
    accent_hover="#3160ef",
    on_accent="#ffffff",
    url="#2563c7",
    engine="#1f8f4e",
    danger_bg="#fdecec",
    danger_border="#f3b9b9",
    danger_text="#a32020",
)


@dataclass(frozen=True)
class Theme:
    """A named, selectable theme: a palette plus its identity, mode, and optional palette credit."""

    id: str
    name: str
    mode: str  # LIGHT or DARK
    palette: Palette
    credit: str | None = None  # third-party palette + license, None for original SearchMob themes


def _t(
    theme_id: str,
    name: str,
    mode: str,
    bg: str,
    surface: str,
    text: str,
    muted: str,
    accent: str,
    border: str,
    credit: str | None = None,
) -> Theme:
    return Theme(
        theme_id,
        name,
        mode,
        _from_roles(
            mode, bg=bg, surface=surface, text=text, muted=muted, accent=accent, border=border
        ),
        credit,
    )


# The theme library: the two original SearchMob looks (defaults) plus the curated slate of nine
# and two WCAG-AAA accessibility themes. Reused third-party palettes carry an attribution credit;
# the SearchMob and accessibility palettes are original.
_THEME_LIST: list[Theme] = [
    Theme("searchmob-light", "SearchMob Light", LIGHT, LIGHT_PALETTE),
    Theme("searchmob-dark", "SearchMob Dark", DARK, DARK_PALETTE),
    _t(
        "github-light",
        "GitHub Light",
        LIGHT,
        "#ffffff",
        "#f6f8fa",
        "#24292f",
        "#57606a",
        "#0969da",
        "#d0d7de",
        "GitHub Primer palette (MIT)",
    ),
    _t(
        "one-dark",
        "One Dark",
        DARK,
        "#282c34",
        "#2c313a",
        "#abb2bf",
        "#5c6370",
        "#61afef",
        "#3e4451",
        "One Dark Pro palette (MIT)",
    ),
    _t(
        "dracula",
        "Dracula",
        DARK,
        "#282a36",
        "#44475a",
        "#f8f8f2",
        "#6272a4",
        "#bd93f9",
        "#44475a",
        "Dracula palette (MIT)",
    ),
    _t(
        "tokyo-night",
        "Tokyo Night",
        DARK,
        "#1a1b2e",
        "#24283b",
        "#c0caf5",
        "#565f89",
        "#7aa2f7",
        "#292e42",
        "Tokyo Night palette (MIT)",
    ),
    _t(
        "catppuccin-mocha",
        "Catppuccin Mocha",
        DARK,
        "#1e1e2e",
        "#313244",
        "#cdd6f4",
        "#7f849c",
        "#89b4fa",
        "#45475a",
        "Catppuccin palette (MIT)",
    ),
    _t(
        "catppuccin-latte",
        "Catppuccin Latte",
        LIGHT,
        "#eff1f5",
        "#e6e9ef",
        "#4c4f69",
        "#9ca0b0",
        "#1e66f5",
        "#ccd0da",
        "Catppuccin palette (MIT)",
    ),
    _t(
        "gruvbox",
        "Gruvbox",
        DARK,
        "#282828",
        "#3c3836",
        "#ebdbb2",
        "#928374",
        "#83a598",
        "#504945",
        "Gruvbox palette (MIT)",
    ),
    _t(
        "nord",
        "Nord",
        DARK,
        "#2e3440",
        "#3b4252",
        "#eceff4",
        "#7b88a1",
        "#88c0d0",
        "#434c5e",
        "Nord palette (MIT)",
    ),
    _t(
        "rose-pine-dawn",
        "Rose Pine Dawn",
        LIGHT,
        "#faf4ed",
        "#fffaf3",
        "#575279",
        "#9893a5",
        "#d7827a",
        "#f2e9e1",
        "Rose Pine palette (MIT)",
    ),
    _t(
        "obsidian-slate",
        "Obsidian Slate",
        DARK,
        "#0d1117",
        "#161b22",
        "#f0f6fc",
        "#b1bac4",
        "#58a6ff",
        "#30363d",
    ),
    _t(
        "paper-white",
        "Paper White",
        LIGHT,
        "#ffffff",
        "#f3f4f6",
        "#101010",
        "#595959",
        "#0058cc",
        "#bbbbbb",
    ),
]

THEMES: dict[str, Theme] = {theme.id: theme for theme in _THEME_LIST}
LIGHT_THEME_IDS: list[str] = [t.id for t in _THEME_LIST if t.mode == LIGHT]
DARK_THEME_IDS: list[str] = [t.id for t in _THEME_LIST if t.mode == DARK]
DEFAULT_LIGHT_ID = "searchmob-light"
DEFAULT_DARK_ID = "searchmob-dark"

# The active palette/theme, set by `apply_theme`, read by the result delegate. Defaults to the dark
# SearchMob look so an early paint before `apply_theme` still uses on-palette colors.
_active: Palette = DARK_PALETTE
_active_theme: Theme = THEMES[DEFAULT_DARK_ID]


def clamp_font_pt(pt: object) -> int:
    """Clamp a font-size preference to the supported point range (unparseable -> default)."""
    if isinstance(pt, bool) or not isinstance(pt, (int, float, str)):
        return DEFAULT_FONT_PT
    try:
        value = int(pt)
    except (TypeError, ValueError):
        return DEFAULT_FONT_PT
    return max(MIN_FONT_PT, min(MAX_FONT_PT, value))


def build_qss(p: Palette, font_pt: int = DEFAULT_FONT_PT) -> str:
    """Generate the full stylesheet from a palette, sized for the given base font (in points)."""
    base_px = round(font_pt * 4 / 3)
    heading_px = base_px + 2
    chip_px = base_px - 1
    return f"""
* {{
    font-size: {base_px}px;
}}
QWidget {{
    background-color: {p.bg};
    color: {p.text};
}}
QMainWindow, QDialog {{ background-color: {p.bg}; }}

/* Header / actions toolbar: flat, no frame; actions look like clean text buttons. */
QToolBar {{
    background-color: {p.bg};
    border: none;
    padding: 6px 8px;
    spacing: 4px;
}}
QToolBar QToolButton {{
    background-color: transparent;
    color: {p.text};
    border: none;
    border-radius: 8px;
    padding: 7px 12px;
}}
QToolBar QToolButton:hover {{ background-color: {p.surface}; }}
QToolBar QToolButton:pressed {{ background-color: {p.card_hover}; }}

/* Text inputs. */
QLineEdit {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 10px 14px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:focus {{ border: 1px solid {p.accent}; }}

/* Buttons: secondary by default, accent-filled when role="primary". */
QPushButton {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 9px 16px;
}}
QPushButton:hover {{ background-color: {p.card_hover}; }}
QPushButton:disabled {{ color: {p.muted}; }}
QPushButton[role="primary"] {{
    background-color: {p.accent};
    color: {p.on_accent};
    border: none;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{ background-color: {p.accent_hover}; }}
QPushButton[role="primary"]:disabled {{ background-color: {p.border}; color: {p.muted}; }}

/* Category tabs (verticals): pill-shaped chips; the active one is accent-filled. */
QPushButton[role="chip"] {{
    padding: 5px 14px;
    border-radius: 14px;
    font-size: {chip_px}px;
    color: {p.muted};
}}
QPushButton[role="chip"]:checked {{
    background-color: {p.accent};
    color: {p.on_accent};
    border: none;
    font-weight: 600;
}}
QPushButton[role="chip"]:checked:hover {{ background-color: {p.accent_hover}; }}

/* Results list: cards float on the window background. */
QListView {{
    background-color: {p.bg};
    border: none;
    outline: none;
}}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QComboBox {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px 10px;
}}

QStatusBar {{
    background-color: {p.surface};
    color: {p.muted};
    border-top: 1px solid {p.border};
}}
QStatusBar::item {{ border: none; }}

QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="heading"] {{ font-size: {heading_px}px; font-weight: 600; }}
QLabel[role="url"] {{ color: {p.url}; }}
QLabel[role="engine"] {{ color: {p.engine}; }}

QFrame[role="caveat"] {{
    background-color: {p.danger_bg};
    border: 1px solid {p.danger_border};
    border-radius: 10px;
}}
QLabel[role="caveat-text"] {{ color: {p.danger_text}; }}

/* "Update available" banner, pinned at the top of the window. Accent fill so it reads as a
   notice; the Update button keeps its primary styling against it. */
QFrame#updateBanner {{
    background-color: {p.accent};
    border: none;
    border-radius: 10px;
}}
QFrame#updateBanner QLabel {{ background: transparent; color: {p.on_accent}; font-weight: 600; }}
QFrame#updateBanner QPushButton {{
    background-color: {p.on_accent};
    color: {p.accent};
    border: none;
    border-radius: 9px;
    padding: 7px 16px;
    font-weight: 700;
}}
QFrame#updateBanner QPushButton:hover {{ background-color: {p.card_hover}; }}
QFrame#updateBanner QPushButton[role="dismiss"] {{
    background: transparent;
    color: {p.on_accent};
    padding: 6px 10px;
    font-weight: 700;
}}
QFrame#updateBanner QPushButton[role="dismiss"]:hover {{ background-color: {p.accent_hover}; }}

/* Contextual Wikipedia summary card, above the results. */
QFrame#summaryCard {{
    background-color: {p.card};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 6px 4px;
}}
QFrame#summaryCard QLabel {{ background: transparent; }}

/* Settings dialog: left-hand navigation column. */
QListWidget#settingsNav {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}
QListWidget#settingsNav::item {{
    padding: 8px 12px;
    border-radius: 7px;
    color: {p.text};
}}
QListWidget#settingsNav::item:selected {{
    background-color: {p.accent};
    color: {p.on_accent};
}}
QListWidget#settingsNav::item:hover:!selected {{
    background-color: {p.card_hover};
}}

/* Slim, modern scrollbars. */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# Built once per default palette; used by `theme_stylesheet` for the back-compat mode API.
_LIGHT_QSS = build_qss(LIGHT_PALETTE)
_DARK_QSS = build_qss(DARK_PALETTE)


def resolve_theme(name: str | None) -> str:
    """Map a stored mode preference to one of `LIGHT`, `DARK`, `SYSTEM` (unknown/None -> SYSTEM)."""
    if name is None:
        return SYSTEM
    candidate = name.strip().lower()
    if candidate in _VALID:
        return candidate
    return SYSTEM


def theme_stylesheet(name: str) -> str:
    """QSS for an explicit mode `name`. `SYSTEM` returns "" (resolved at apply time)."""
    resolved = resolve_theme(name)
    if resolved == LIGHT:
        return _LIGHT_QSS
    if resolved == DARK:
        return _DARK_QSS
    return ""


def _slot_theme(theme_id: str, mode: str) -> Theme:
    """The theme for a slot, falling back to the slot's default if the id is unknown/mismatched."""
    theme = THEMES.get(theme_id)
    if theme is not None and theme.mode == mode:
        return theme
    return THEMES[DEFAULT_DARK_ID if mode == DARK else DEFAULT_LIGHT_ID]


def resolve_active_theme(mode: str | None, light_id: str, dark_id: str, os_is_dark: bool) -> Theme:
    """Resolve the mode + the two slot ids (+ OS scheme for SYSTEM) to the active `Theme`."""
    resolved = resolve_theme(mode)
    if resolved == LIGHT:
        return _slot_theme(light_id, LIGHT)
    if resolved == DARK:
        return _slot_theme(dark_id, DARK)
    return _slot_theme(dark_id, DARK) if os_is_dark else _slot_theme(light_id, LIGHT)


def active_palette() -> Palette:
    """The palette currently applied (read by the result delegate). Defaults to dark."""
    return _active


def active_theme() -> Theme:
    """The named theme currently applied (used to label the quick light/dark toggle)."""
    return _active_theme


def _os_is_dark(app: QApplication) -> bool:
    from PySide6.QtCore import Qt

    return app.styleHints().colorScheme() == Qt.ColorScheme.Dark


def effective_palette(app: QApplication, theme: str) -> Palette:
    """Resolve a bare mode to a default palette. `SYSTEM` follows the OS light/dark color scheme."""
    resolved = resolve_theme(theme)
    if resolved == LIGHT:
        return LIGHT_PALETTE
    if resolved == DARK:
        return DARK_PALETTE
    return DARK_PALETTE if _os_is_dark(app) else LIGHT_PALETTE


def apply_theme(
    app: QApplication,
    theme: str,
    light_id: str = DEFAULT_LIGHT_ID,
    dark_id: str = DEFAULT_DARK_ID,
    font_pt: int = DEFAULT_FONT_PT,
) -> None:
    """Resolve mode + slots, set the base font, apply QSS, and record the active theme."""
    from PySide6.QtGui import QFont

    global _active, _active_theme
    resolved = resolve_active_theme(theme, light_id, dark_id, _os_is_dark(app))
    pt = clamp_font_pt(font_pt)
    _active = resolved.palette
    _active_theme = resolved

    base_font: QFont = app.font()
    base_font.setPointSize(pt)
    app.setFont(base_font)
    app.setStyleSheet(build_qss(resolved.palette, pt))

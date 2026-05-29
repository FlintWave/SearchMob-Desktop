"""Theme for the PySide6 shell: a small, COSMIC-leaning design system.

Rather than the old "don't fight native Qt" minimal sheet (which read as dated), this defines a
flat, rounded, accent-driven look with consistent spacing, card-style result rows, and light/dark
palettes. `SYSTEM` follows the OS light/dark scheme (via `QApplication.styleHints().colorScheme()`)
but still applies our QSS, so the modern look is the default.

The pure helpers (`resolve_theme`, `theme_stylesheet`) stay import-safe (no PySide6 import) so
headless tests can exercise them. `apply_theme` and `effective_palette` touch the running
`QApplication` and resolve `SYSTEM` to a concrete palette.
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


# COSMIC-leaning palettes: flat surfaces, one blue accent, generous contrast.
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

# The active palette, set by `apply_theme`, read by the result delegate. Defaults to dark so an
# early paint before `apply_theme` still uses on-palette colors rather than guessing.
_active: Palette = DARK_PALETTE


def build_qss(p: Palette) -> str:
    """Generate the full stylesheet from a palette."""
    return f"""
* {{
    font-size: 14px;
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
QLabel[role="heading"] {{ font-size: 16px; font-weight: 600; }}
QLabel[role="url"] {{ color: {p.url}; }}
QLabel[role="engine"] {{ color: {p.engine}; }}

QFrame[role="caveat"] {{
    background-color: {p.danger_bg};
    border: 1px solid {p.danger_border};
    border-radius: 10px;
}}
QLabel[role="caveat-text"] {{ color: {p.danger_text}; }}

/* Slim, modern scrollbars. */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


# Built once per palette; the QSS is static for a given palette.
_LIGHT_QSS = build_qss(LIGHT_PALETTE)
_DARK_QSS = build_qss(DARK_PALETTE)


def resolve_theme(name: str | None) -> str:
    """Map a stored preference to one of `LIGHT`, `DARK`, `SYSTEM` (unknown/None -> SYSTEM)."""
    if name is None:
        return SYSTEM
    candidate = name.strip().lower()
    if candidate in _VALID:
        return candidate
    return SYSTEM


def theme_stylesheet(name: str) -> str:
    """QSS for an explicit `name`. `SYSTEM` returns "" (resolved to a palette at apply time)."""
    resolved = resolve_theme(name)
    if resolved == LIGHT:
        return _LIGHT_QSS
    if resolved == DARK:
        return _DARK_QSS
    return ""


def active_palette() -> Palette:
    """The palette currently applied (read by the result delegate). Defaults to dark."""
    return _active


def effective_palette(app: QApplication, theme: str) -> Palette:
    """Resolve `theme` to a concrete palette. `SYSTEM` follows the OS light/dark color scheme."""
    from PySide6.QtCore import Qt

    resolved = resolve_theme(theme)
    if resolved == LIGHT:
        return LIGHT_PALETTE
    if resolved == DARK:
        return DARK_PALETTE
    scheme = app.styleHints().colorScheme()
    return LIGHT_PALETTE if scheme == Qt.ColorScheme.Light else DARK_PALETTE


def apply_theme(app: QApplication, theme: str) -> None:
    """Resolve `theme` (incl. SYSTEM -> OS scheme), apply its QSS, and record the active palette."""
    global _active
    palette = effective_palette(app, theme)
    _active = palette
    app.setStyleSheet(build_qss(palette))

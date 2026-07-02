"""Hand-built HTML for the home and results pages. No template engine, by design.

Mirrors the layout produced by the Android Ktor server (`SearchServer.kt` `renderHomePage` /
`renderResultsPage`): the same `<link rel="search">` OpenSearch advertisement, the same embedded
stylesheet (CSS variables for light/dark, `prefers-color-scheme` plus a `[data-theme]` override
set by the toggle), and the same pre-paint theme restore script.

Every interpolated string runs through `html.escape` with `quote=True` so a hostile query or
title cannot break out of an attribute or inject markup. Result anchors are only rendered when
the URL passes the http/https scheme allowlist (see `app.is_safe_http_url`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache
from html import escape
from urllib.parse import quote_plus, urlsplit

from searchmob_desktop.data.history import HistoryEntry
from searchmob_desktop.engines import EngineOutcome, SearchResult
from searchmob_desktop.engines.media_intent import ActionsRow, MediaCategory
from searchmob_desktop.engines.rank import Lens, RankingRules, RankRule, host_of_url
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.gui.theme import (
    DEFAULT_DARK_ID,
    DEFAULT_LIGHT_ID,
    LIGHT,
    THEMES,
    Palette,
    Theme,
)
from searchmob_desktop.i18n import (
    N_,
    SUPPORTED_LOCALES,
    is_rtl,
    normalize_tag,
    set_request_locale,
    tr,
    trc,
    trn,
)
from searchmob_desktop.prefs import UserPreferences

# The per-result domain actions offered in the served UI, in display order. Mirrors the in-app
# right-click menu (block / lower / raise / pin); "Reset" maps to NORMAL (removes the rule).
_RANK_ACTIONS: tuple[tuple[RankRule, str], ...] = (
    (RankRule.BLOCK, N_("Block")),
    (RankRule.LOWER, N_("Lower")),
    (RankRule.RAISE, N_("Raise")),
    (RankRule.PIN, N_("Pin")),
)


# The CSS custom properties served per theme, derived from each GUI `Palette` so the browser look
# matches the shell exactly. The shadow tracks the mode (deeper on dark); `--topbar` is the page
# background with an alpha byte so the sticky bar reads through the backdrop blur.
def _theme_vars(theme: Theme) -> str:
    """The `--bg`/`--fg`/... custom-property declarations for one theme's palette."""
    p: Palette = theme.palette
    shadow = "0 1px 6px rgba(32,33,36,.12)" if theme.mode == LIGHT else "0 1px 6px rgba(0,0,0,.5)"
    return (
        f"--bg:{p.bg};--fg:{p.text};--muted:{p.muted};--border:{p.border};--card:{p.surface};"
        f"--link:{p.accent};--url:{p.url};--snippet:{p.muted};"
        f"--chip-bg:{p.card_hover};--chip-fg:{p.muted};"
        f"--accent:{p.accent};--shadow:{shadow};--topbar:{p.bg}ee;"
    )


@lru_cache(maxsize=1)
def _theme_css() -> str:
    """The generated theme blocks: `:root` (default light), the dark media query, and one
    `[data-theme="<id>"]` block per theme. Cached since `THEMES` is constant for the process."""
    parts = [
        ":root{" + _theme_vars(THEMES[DEFAULT_LIGHT_ID]) + "}",
        "@media (prefers-color-scheme:dark){:root{" + _theme_vars(THEMES[DEFAULT_DARK_ID]) + "}}",
    ]
    for theme in THEMES.values():
        parts.append(f'[data-theme="{theme.id}"]{{' + _theme_vars(theme) + "}")
    return "".join(parts)


# Self-contained stylesheet: no external fonts / CDNs / runtime fetches. The per-theme variable
# blocks (`:root`, the `prefers-color-scheme: dark` media query, and a `[data-theme]` override per
# theme so the JS picker is authoritative) are prepended at render time from `_theme_css`. This is
# the static remainder; kept tight on whitespace to keep the served bytes small.
#
# The look is Material 3, mirroring the Android served pages: an elevated search bar with hover and
# focus-within states, rounded 16px cards, pill buttons, and chip state layers. State layers are a
# `color-mix` of the theme accent over transparent, emitted after a plain rgba fallback for older
# browsers, so every one of the theme palettes keeps driving the colors. Interactive surfaces get
# short transitions; the reduced-motion media query flattens them all.
_PAGE_CSS = (
    "*{box-sizing:border-box}"
    "html,body{margin:0;padding:0}"
    "html{font-size:12pt}"
    "body{background:var(--bg);color:var(--fg);line-height:1.55;font-size:1rem;"
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}'
    "a{color:var(--link);text-decoration:none}"
    "a:hover{text-decoration:underline}"
    ".topbar{display:flex;align-items:center;gap:14px;padding:10px 18px;"
    "border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--topbar);"
    "backdrop-filter:saturate(1.4) blur(8px);z-index:10}"
    ".topbar .logo{font-weight:800;font-size:20px;color:var(--accent);letter-spacing:-.5px;"
    "white-space:nowrap}"
    ".theme-toggle{margin-inline-start:auto;background:transparent;border:1px solid var(--border);"
    "color:var(--fg);border-radius:20px;padding:6px 14px;cursor:pointer;font-size:13px;"
    "white-space:nowrap;transition:background-color 150ms,border-color 150ms,color 150ms}"
    ".theme-toggle:hover{border-color:var(--accent);color:var(--accent);"
    "background-color:rgba(127,127,127,.08)}"
    ".theme-toggle:hover{background-color:color-mix(in srgb,var(--accent) 8%,transparent)}"
    ".settings-link{margin-inline-start:auto;border:1px solid var(--border);color:var(--fg);"
    "border-radius:20px;padding:6px 14px;font-size:13px;text-decoration:none;white-space:nowrap;"
    "transition:border-color 150ms,color 150ms}"
    ".settings-link:hover{border-color:var(--accent);color:var(--accent)}"
    ".settings-link+.theme-toggle{margin-inline-start:0}"
    ".topbar .spacer{margin-inline-start:auto}"
    # The language picker sits in the trailing cluster; its auto inline-start margin pushes the
    # whole group (language, settings, theme) to the end, mirroring under rtl.
    ".topbar .langform{margin-inline-start:auto;display:inline-flex;align-items:center;gap:6px;"
    "margin-bottom:0;font-size:13px}"
    ".topbar .langform label{color:var(--muted)}"
    ".topbar .langform select{background:transparent;color:var(--fg);"
    "border:1px solid var(--border);"
    "border-radius:20px;padding:5px 10px;font-size:13px;cursor:pointer}"
    ".topbar .langform+.settings-link,.topbar .langform+.theme-toggle{margin-inline-start:0}"
    # Owner-only "update available" banner, pinned above the top bar. Accent fill so it reads as a
    # notice without an icon set; the action is a high-contrast pill linking to the release.
    ".updatebar{display:flex;align-items:center;gap:12px;padding:9px 18px;background:var(--accent);"
    "color:#fff;font-size:13px}"
    ".updatebar .msg{font-weight:600}"
    ".updatebar .btn{margin-inline-start:auto;background:#fff;color:var(--accent);"
    "border-radius:20px;padding:6px 16px;font-weight:700;text-decoration:none;white-space:nowrap;"
    "transition:box-shadow 150ms,filter 150ms}"
    ".updatebar .btn:hover{text-decoration:none;filter:brightness(.96);"
    "box-shadow:0 1px 3px rgba(0,0,0,.25)}"
    ".settings{max-width:680px;margin:0 auto;padding:24px 18px 60px}"
    ".settings h1{font-size:1.5rem;margin:8px 0 18px}"
    ".settings .saved{color:#fff;background:var(--accent);display:inline-block;border-radius:8px;"
    "padding:5px 14px;font-size:13px;margin:0 0 16px}"
    ".settings .card{background:var(--card);border:1px solid var(--border);border-radius:16px;"
    "padding:18px 20px;margin:0 0 16px;box-shadow:var(--shadow)}"
    ".settings .card h2{font-size:.9375rem;margin:0 0 14px;color:var(--accent)}"
    ".settings .field{margin:0 0 14px}"
    ".settings .field>label{display:block;font-size:.8125rem;margin:0 0 6px;font-weight:600}"
    ".settings select{width:100%;padding:10px 12px;border:1px solid var(--border);"
    "border-radius:12px;background:var(--bg);color:var(--fg);font-size:.875rem;"
    "transition:border-color 150ms}"
    ".settings select:hover{border-color:var(--accent)}"
    ".settings .checkrow{display:flex;align-items:center;gap:9px;font-size:.875rem;margin:0 0 10px;"
    "cursor:pointer}"
    ".settings .hint{font-size:.75rem;color:var(--muted);margin:6px 0 0}"
    ".settings .actions{margin-top:6px}"
    ".settings .actions button{background:var(--accent);color:#fff;border:0;border-radius:24px;"
    "padding:11px 28px;font-size:.9375rem;font-weight:600;cursor:pointer;"
    "transition:box-shadow 150ms,filter 150ms}"
    ".settings .actions button:hover{"
    "box-shadow:0 1px 3px rgba(0,0,0,.2),0 4px 10px rgba(0,0,0,.12)}"
    ".settings .card h3.sub{font-size:13px;margin:16px 0 8px;color:var(--muted)}"
    # Appearance: the text-size A-/A+ stepper. Square buttons flanking the current point size.
    ".settings .sizerow{display:flex;align-items:center;gap:10px}"
    ".settings .sizerow button{width:40px;height:40px;border:1px solid var(--border);"
    "border-radius:12px;background:var(--bg);color:var(--fg);font-size:1rem;cursor:pointer;"
    "transition:border-color 150ms,color 150ms,box-shadow 150ms}"
    ".settings .sizerow button:hover{border-color:var(--accent);color:var(--accent)}"
    ".settings .sizerow button:hover{"
    "box-shadow:0 0 0 4px color-mix(in srgb,var(--accent) 10%,transparent)}"
    ".settings .sizerow .sizeval{font-size:.875rem;color:var(--muted);min-width:54px}"
    ".settings .rulelist{list-style:none;margin:0 0 14px;padding:0}"
    ".settings .rulelist li{display:flex;align-items:center;gap:8px;flex-wrap:wrap;"
    "padding:8px 0;border-bottom:1px solid var(--border)}"
    ".settings .rulelist .dom{font-weight:600;font-size:13px;word-break:break-all}"
    ".settings .rulelist .rank{margin-inline-start:auto}"
    ".settings .addrule{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
    ".settings .addrule input[type=text]{flex:1;min-width:140px;padding:9px 12px;"
    "border:1px solid var(--border);border-radius:12px;background:var(--bg);color:var(--fg);"
    "font-size:14px;transition:border-color 150ms}"
    ".settings .addrule input[type=text]:hover{border-color:var(--accent)}"
    ".settings .addrule select{width:auto;min-width:110px}"
    ".settings .addrule button,.settings .lensform button,.settings .lensdel button{"
    "background:var(--accent);color:#fff;border:0;border-radius:20px;padding:9px 20px;"
    "font-size:13px;font-weight:600;cursor:pointer;transition:filter 150ms}"
    ".settings .addrule button:hover,.settings .lensform button:hover{filter:brightness(1.06)}"
    ".settings .lensitem{display:flex;gap:10px;align-items:flex-start;padding:10px 0;"
    "border-bottom:1px solid var(--border)}"
    ".settings .lensform{flex:1;display:flex;flex-direction:column;gap:8px}"
    ".settings .lensform .lname{font-weight:600}"
    ".settings .lensform input[type=text]{width:100%;padding:9px 12px;"
    "border:1px solid var(--border);"
    "border-radius:12px;background:var(--bg);color:var(--fg);font-size:14px}"
    ".settings .lensform .lf{display:flex;flex-direction:column;gap:3px;font-size:12px;"
    "color:var(--muted)}"
    ".settings .lensform button{align-self:flex-start}"
    ".settings .lensdel button{background:transparent;color:var(--muted);"
    "border:1px solid var(--border)}"
    ".settings .lensdel button:hover{border-color:#d33;color:#d33}"
    ".settings .hint code{background:var(--chip-bg);color:var(--chip-fg);padding:2px 6px;"
    "border-radius:6px;font-size:12px}"
    ".settings .gogglelist,.settings .histlist{list-style:none;margin:0 0 12px;padding:0;"
    "font-size:13px}"
    ".settings .gogglelist li{display:flex;gap:8px;align-items:center;padding:5px 0;"
    "border-bottom:1px solid var(--border)}"
    ".settings .gogglelist .site{font-weight:600;word-break:break-all}"
    ".settings .gogglelist .act{margin-inline-start:auto;font-size:11px;color:var(--muted)}"
    ".settings .histlist li{padding:4px 0;border-bottom:1px solid var(--border);"
    "word-break:break-word}"
    ".settings .goggleimport{display:flex;flex-direction:column;gap:8px}"
    ".settings textarea{width:100%;padding:9px 11px;border:1px solid var(--border);"
    "border-radius:12px;"
    "background:var(--bg);color:var(--fg);font-size:13px;font-family:ui-monospace,monospace;"
    "resize:vertical}"
    ".settings .goggleimport .grow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}"
    ".settings .goggleimport button,.settings .goggleclear button,.settings .histclear button{"
    "background:var(--accent);color:#fff;border:0;border-radius:20px;padding:9px 20px;"
    "font-size:13px;"
    "font-weight:600;cursor:pointer;transition:filter 150ms}"
    ".settings .goggleimport button:hover{filter:brightness(1.06)}"
    ".settings .goggleclear button,.settings .histclear button{background:transparent;"
    "color:var(--muted);border:1px solid var(--border)}"
    ".settings .goggleclear button:hover,.settings .histclear button:hover{"
    "border-color:#d33;color:#d33}"
    ".settings .goggleclear,.settings .histclear{margin:0 0 8px}"
    # Elevated M3 search bar: resting shadow from the theme, a raised shadow on hover, and an
    # accent border with deeper elevation while the query field holds focus.
    ".searchbox{display:flex;align-items:stretch;background:var(--card);"
    "border:1px solid var(--border);border-radius:28px;box-shadow:var(--shadow);overflow:hidden;"
    "transition:box-shadow 150ms,border-color 150ms}"
    ".searchbox:hover{box-shadow:0 1px 3px rgba(0,0,0,.15),0 4px 8px rgba(0,0,0,.1)}"
    ".searchbox:focus-within{border-color:var(--accent);"
    "box-shadow:0 2px 6px rgba(0,0,0,.18),0 6px 14px rgba(0,0,0,.12)}"
    ".searchbox input[type=text]{flex:1;min-width:0;border:0;outline:0;background:transparent;"
    "color:var(--fg);font-size:1rem;padding:13px 18px}"
    ".searchbox input[type=submit]{border:0;background:var(--accent);color:#fff;padding:0 22px;"
    "cursor:pointer;font-size:.9375rem;font-weight:600;transition:filter 150ms}"
    ".searchbox input[type=submit]:hover{filter:brightness(1.07)}"
    # Scope (lens) selector nested inside the search box, just left of the Search button. A subtle
    # divider separates it from the query field; it belongs to a separate /scope form via `form=`.
    ".searchbox select{border:0;border-inline-start:1px solid var(--border);background:transparent;"
    "color:var(--fg);font-size:.875rem;padding:0 12px;outline:0;max-width:190px;cursor:pointer;"
    "transition:background-color 150ms}"
    ".searchbox select:hover{background-color:rgba(127,127,127,.06)}"
    ".searchbox select:hover{background-color:color-mix(in srgb,var(--fg) 6%,transparent)}"
    ".home{max-width:600px;margin:0 auto;padding:13vh 20px 0;text-align:center}"
    ".home .brand{font-size:3rem;font-weight:800;color:var(--accent);letter-spacing:-1.5px}"
    ".home .tagline{color:var(--muted);margin:8px 0 28px;font-size:.9375rem}"
    ".home .searchbox{max-width:560px;margin:0 auto;text-align:start}"
    ".topbar .searchbox{flex:1;max-width:620px}"
    ".topbar .searchbox input[type=text]{padding:9px 16px}"
    ".topbar .searchbox input[type=submit]{padding:0 16px}"
    # The collapsible "Search operators" cheat sheet under the home search box: a rounded card
    # whose native <details> marker is replaced by a rotating chevron; each row pairs a monospace
    # operator chip with its plain-words description.
    ".ophelp{max-width:560px;margin:14px auto 0;text-align:start;border:1px solid var(--border);"
    "border-radius:16px;background:var(--card);padding:0 16px}"
    ".ophelp summary{cursor:pointer;padding:10px 0;font-size:.8125rem;font-weight:600;"
    "color:var(--muted);list-style:none}"
    ".ophelp summary::-webkit-details-marker{display:none}"
    # U+25B8 BLACK RIGHT-POINTING SMALL TRIANGLE, then an escaped space (a literal space would
    # just terminate the CSS hex escape). Written as CSS escapes so the source stays ASCII.
    ".ophelp summary::before{content:'\\25b8\\20';display:inline-block;transition:transform 150ms}"
    ".ophelp[open] summary::before{transform:rotate(90deg)}"
    ".ophelp .oprow{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;padding:6px 0;"
    "border-top:1px solid var(--border);font-size:.8125rem;color:var(--muted)}"
    ".ophelp .oprow:first-of-type{border-top:0}"
    ".ophelp .code{font-family:ui-monospace,monospace;background:var(--chip-bg);"
    "color:var(--chip-fg);padding:2px 7px;border-radius:8px;font-size:.75rem;white-space:nowrap}"
    ".results{max-width:660px;margin:0 auto;padding:18px 20px 64px}"
    ".results .meta{color:var(--muted);font-size:.8125rem;margin:2px 0 20px}"
    ".engine-status{margin:-12px 0 16px}"
    ".engine-status summary{cursor:pointer;color:var(--muted)}"
    ".engine-status ul{list-style:none;margin:6px 0 0;padding:0;color:var(--muted)}"
    ".engine-status .engine-failed{font-weight:600}"
    ".actions-row{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 18px}"
    ".actions-row .alabel{color:var(--muted);font-size:.8125rem;font-weight:600}"
    ".actions-row a{font-size:.8125rem;padding:5px 12px;border:1px solid var(--border);"
    "border-radius:8px;text-decoration:none;color:var(--link);"
    "transition:background-color 150ms,border-color 150ms}"
    ".actions-row a:hover{text-decoration:none;border-color:var(--accent);"
    "background-color:rgba(127,127,127,.06)}"
    ".actions-row a:hover{background-color:color-mix(in srgb,var(--accent) 8%,transparent)}"
    ".didyoumean{font-size:.9375rem;margin:2px 0 18px}"
    ".didyoumean a{font-weight:600;font-style:italic}"
    # Each result is a quiet rounded surface that tints with the accent state layer on hover; the
    # negative inline margins keep the text column aligned with the page while the hover pad grows.
    ".result{margin:0 -14px 4px;padding:12px 14px;border-radius:16px;"
    "transition:background-color 150ms}"
    ".result:hover{background-color:rgba(127,127,127,.05)}"
    ".result:hover{background-color:color-mix(in srgb,var(--accent) 4%,transparent)}"
    # Infinite scroll hides results past the first reveal window; the reveal script unhides them in
    # batches as the sentinel scrolls into view. With JS off, the rule is harmless and all show.
    ".result.is-collapsed{display:none}"
    ".reveal-sentinel{height:1px}"
    ".result .url{color:var(--url);font-size:.8125rem;white-space:nowrap;overflow:hidden;"
    "text-overflow:ellipsis}"
    ".result .title{display:block;font-size:1.25rem;line-height:1.35;margin:2px 0 4px;"
    "font-weight:500}"
    ".result .snippet{margin:2px 0 8px;color:var(--snippet);font-size:.875rem;line-height:1.5}"
    ".engines{display:flex;flex-wrap:wrap;gap:6px}"
    ".chip{background:var(--chip-bg);color:var(--chip-fg);font-size:.6875rem;padding:3px 10px;"
    "border-radius:8px;font-weight:500;letter-spacing:.01em}"
    ".empty{color:var(--muted);text-align:center;padding:48px 0}"
    ".summary{display:flex;gap:14px;border:1px solid var(--border);border-radius:16px;"
    "background:var(--card);padding:16px 18px;margin:0 0 22px;box-shadow:var(--shadow);"
    "transition:box-shadow 150ms}"
    ".summary:hover{box-shadow:0 2px 6px rgba(0,0,0,.14)}"
    ".summary .body{flex:1;min-width:0}"
    ".summary .stitle{font-size:1.0625rem;font-weight:600;margin:0;line-height:1.35}"
    ".summary .stitle a{color:var(--fg)}"
    ".summary .sdesc{color:var(--muted);font-size:.75rem;margin:2px 0 6px}"
    ".summary .sextract{font-size:.875rem;margin:0 0 6px;line-height:1.5}"
    ".summary .ssource{font-size:.75rem}"
    ".summary img{width:84px;height:84px;object-fit:cover;border-radius:12px;flex:none}"
    "@media (max-width:560px){.summary img{display:none}}"
    ".verticalbar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}"
    ".verticalbar .chip{font-size:.8125rem;padding:6px 16px;border:1px solid var(--border);"
    "border-radius:16px;background:var(--card);color:var(--fg);text-decoration:none;"
    "transition:background-color 150ms,border-color 150ms}"
    ".verticalbar .chip:hover{text-decoration:none;border-color:var(--accent)}"
    ".verticalbar .chip:hover{background-color:color-mix(in srgb,var(--accent) 8%,transparent)}"
    # Active chip: an accent-tinted state layer over the card keeps the theme's own foreground
    # readable in every palette, light and dark. aria-current also marks it, never color alone.
    ".verticalbar .chip.active{background:var(--chip-bg);color:var(--fg);"
    "border-color:var(--accent);font-weight:600}"
    ".verticalbar .chip.active{background:color-mix(in srgb,var(--accent) 22%,var(--card));"
    "color:var(--fg);border-color:var(--accent);font-weight:600}"
    # Visible keyboard focus (the search input clears the default ring) + reduced-motion support.
    "a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,"
    "textarea:focus-visible,summary:focus-visible{"
    "outline:2px solid var(--accent);outline-offset:2px}"
    "@media(prefers-reduced-motion:reduce){.topbar{backdrop-filter:none}"
    "*{animation-duration:.01ms!important;transition-duration:.01ms!important}}"
    ".scopebar{display:flex;align-items:center;gap:8px;margin:0 0 18px;font-size:13px;"
    "color:var(--muted)}"
    ".scopebar select{font-size:13px;padding:5px 10px;border:1px solid var(--border);"
    "border-radius:10px;background:var(--card);color:var(--fg);transition:border-color 150ms}"
    ".scopebar select:hover{border-color:var(--accent)}"
    ".rank{display:flex;flex-wrap:wrap;gap:6px;margin-top:5px;align-items:center}"
    ".rank form{display:inline;margin:0}"
    ".rank .state{font-size:11px;color:var(--muted);margin-inline-end:2px}"
    ".rank button{font-size:11px;padding:3px 11px;border:1px solid var(--border);"
    "border-radius:10px;background:var(--card);color:var(--muted);cursor:pointer;"
    "transition:background-color 150ms,border-color 150ms,color 150ms}"
    ".rank button:hover{border-color:var(--accent);color:var(--fg)}"
    ".rank button:hover{background-color:color-mix(in srgb,var(--accent) 8%,transparent)}"
    ".rank button.on{background:var(--accent);color:#fff;border-color:var(--accent)}"
    "@media (max-width:560px){.topbar .logo{display:none}}"
)

# The two-slot defaults and font bounds, mirrored from the GUI (`searchmob_desktop.gui.theme`) so
# the served prefs match the shell. Emitted as JS literals into the shared resolve helpers below.
_JS_DEFAULT_LIGHT_ID = DEFAULT_LIGHT_ID
_JS_DEFAULT_DARK_ID = DEFAULT_DARK_ID
_JS_MIN_FONT = 8
_JS_MAX_FONT = 24
_JS_STEP_FONT = 2

# Shared client-side resolve helpers, inlined into every page's theme scripts. `smOsDark` reads the
# OS scheme; `smSlots` reads the two slot ids (each defaulting to its SearchMob default);
# `smResolve` turns a mode (light/dark/system/absent) plus the slots into the active theme id (null
# when no mode is stored, so the CSS :root/@media defaults stand); `smApply` sets data-theme + font.
_THEME_RESOLVE_JS = (
    "function smGet(k){try{return localStorage.getItem(k);}catch(e){return null;}}"
    "function smOsDark(){return !!(window.matchMedia&&"
    "matchMedia('(prefers-color-scheme: dark)').matches);}"
    f"function smSlots(){{return {{light:smGet('sm-light-theme')||'{_JS_DEFAULT_LIGHT_ID}',"
    f"dark:smGet('sm-dark-theme')||'{_JS_DEFAULT_DARK_ID}'}};}}"
    "function smResolve(){var m=smGet('sm-theme');var s=smSlots();"
    "if(m==='light')return s.light;if(m==='dark')return s.dark;"
    "if(m==='system')return smOsDark()?s.dark:s.light;return null;}"
    "function smApply(){var id=smResolve();var r=document.documentElement;"
    "if(id)r.setAttribute('data-theme',id);else r.removeAttribute('data-theme');"
    "var f=smGet('sm-font');if(f)r.style.fontSize=f+'pt';}"
)

# Runs in <head> before first paint to restore the saved theme + font (avoids the flash of wrong
# theme/size). Resolves the active slot id from the mode and applies it, plus any saved font size.
_THEME_INIT_JS = "(function(){try{" + _THEME_RESOLVE_JS + "smApply();}catch(e){}})();"

# Defines smToggle() (flips the effective mode light<->dark, persists it, re-applies the resolved
# slot) and labels the quick toggle button with the alternative theme.
_THEME_TOGGLE_JS = (
    "(function(){" + _THEME_RESOLVE_JS + "function eff(){var m=smGet('sm-theme');"
    "if(m==='light')return 'light';if(m==='dark')return 'dark';return smOsDark()?'dark':'light';}"
    "function label(){var b=document.getElementById('sm-theme-btn');"
    "if(b)b.textContent=eff()==='dark'?'\\u2600 Light':'\\u263e Dark';}"
    "window.smToggle=function(){var n=eff()==='dark'?'light':'dark';"
    "try{localStorage.setItem('sm-theme',n);}catch(e){}smApply();label();};"
    "label();"
    "})();"
)

# Infinite scroll: the page renders the whole ranked pool but hides results past the first window;
# this watches a sentinel at the bottom and unhides the next batch as it scrolls into view. No new
# request (the pool is already in the page), nothing stored, and with JS off every result shows.
_REVEAL_SIZE = 10
_REVEAL_STEP = 10
_REVEAL_JS = (
    "(function(){"
    f"var step={_REVEAL_STEP};"
    "var sentinel=document.querySelector('.reveal-sentinel');"
    "if(!sentinel)return;"
    "function more(){"
    "var h=document.querySelectorAll('.result.is-collapsed');"
    "for(var i=0;i<step&&i<h.length;i++){h[i].classList.remove('is-collapsed');}"
    "if(document.querySelectorAll('.result.is-collapsed').length===0){"
    "o.disconnect();sentinel.remove();}"
    "}"
    "var o=new IntersectionObserver(function(es){"
    "es.forEach(function(e){if(e.isIntersecting){more();}});"
    "},{rootMargin:'300px'});"
    "o.observe(sentinel);"
    "})();"
)


def _page_head(title_text: str) -> str:
    """Shared `<head>`: meta, title, OpenSearch advertisement, styles, pre-paint theme restore."""
    return (
        "<head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title_text)}</title>"
        '<link rel="search" type="application/opensearchdescription+xml" '
        'title="SearchMob" href="/opensearch.xml">'
        f"<style>{_theme_css()}{_PAGE_CSS}</style>"
        f"<script>{_THEME_INIT_JS}</script>"
        "</head>"
    )


def _theme_toggle_button() -> str:
    """The light/dark toggle button. JS labels it to show the alternative theme."""
    return (
        '<button type="button" class="theme-toggle" id="sm-theme-btn" '
        f'onclick="smToggle()" aria-label="{escape(tr("Toggle light/dark theme"), quote=True)}">'
        f"{escape(tr('Theme'))}</button>"
    )


def _update_banner(banner: tuple[str, str] | None) -> str:
    """An "update available" notice bar linking to the new release. Empty when `banner` is None.

    `banner` is `(version, url)`. The server passes it only for the loopback owner (a network
    visitor cannot install anything and should not see the owner's version), so this renderer just
    formats it. The link opens the release page; the GUI offers the verified one-click install.
    """
    if banner is None:
        return ""
    version, url = banner
    msg = escape(tr("SearchMob {version} is available.", version=version))
    return (
        '<div class="updatebar" role="status">'
        f'<span class="msg">{msg}</span>'
        f'<a class="btn" href="{escape(url, quote=True)}" rel="noopener noreferrer">'
        f"{escape(tr('Get the update'))}</a>"
        "</div>"
    )


def _settings_link(show: bool) -> str:
    """A Settings-page link, shown only to the loopback owner (the route itself is owner-only)."""
    if not show:
        return ""
    label = escape(tr("Settings"))
    return f'<a href="/settings" class="settings-link" aria-label="{label}">{label}</a>'


def _html_open(locale: str) -> str:
    """The doctype + `<html>` tag carrying the page language and direction (rtl for ar/ur)."""
    tag = normalize_tag(locale)
    direction = ' dir="rtl"' if is_rtl(tag) else ""
    return f'<!DOCTYPE html><html lang="{tag}"{direction}>'


def _language_select(current: str) -> str:
    """A language picker `<select>` listing every shipped locale by its endonym, current selected.

    Posts to `/language` (auto-submits via onchange when JS is on) so the whole interface switches
    to the chosen language. Each option shows the language's own name so a speaker recognizes it.
    """
    active = normalize_tag(current)
    options = []
    for loc in SUPPORTED_LOCALES:
        selected = " selected" if loc.tag == active else ""
        options.append(f'<option value="{loc.tag}"{selected}>{escape(loc.native_name)}</option>')
    label = escape(tr("Language"))
    return (
        '<form class="langform" action="/language" method="post">'
        f'<label for="sm-lang">{label}:</label>'
        '<select id="sm-lang" name="lang" aria-label="Interface language" '
        'onchange="this.form.submit()">' + "".join(options) + "</select>"
        f'<noscript><button type="submit">{escape(tr("Apply"))}</button></noscript>'
        "</form>"
    )


def _display_url(raw_url: str) -> str:
    """A human-friendly breadcrumb form of a URL (host then path segments). Best-effort."""
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        return raw_url
    host = (parts.hostname or "").removeprefix("www.")
    if not host:
        return raw_url
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return host
    # U+203A SINGLE RIGHT-POINTING ANGLE QUOTATION MARK matches the Android breadcrumb separator
    # so both UIs read the same. Built via chr(0x203A) so ruff's RUF001 ambiguity-check (which
    # otherwise wants a plain `>`) doesn't trip on the literal in source.
    arrow = chr(0x203A)
    separator = f" {arrow} "
    return host + separator + separator.join(segments)


# One (operator example, short description) row for the "Search operators" cheat sheet, in the
# order shown. Mirrors the Google-style query operators the search engine layer understands (see
# `engines.query_operators`) and the Android home page's table. The examples are syntax, not
# prose, so only the descriptions are translated.
_OPERATOR_HELP: tuple[tuple[str, str], ...] = (
    ('"exact phrase"', N_("match this exact phrase")),
    ("-term", N_("exclude results containing term")),
    ("site:example.com", N_("only results from this site")),
    ("-site:example.com", N_("exclude results from this site")),
    ("intitle:word", N_("word must appear in the title")),
    ("inurl:word", N_("word must appear in the URL")),
    ("filetype:pdf", N_("only this file type (also ext:)")),
    ("before:2023-01-31", N_("published before this date")),
    ("after:2022", N_("published on or after this date (year, year-month, or full date)")),
    ("a OR b", N_("match either term (also a | b)")),
)


def _search_operators_help() -> str:
    """Collapsed "Search operators" help card under the home search box.

    A native `<details>` needs no JavaScript to expand/collapse and stays reachable and operable
    from the keyboard. Starts collapsed so it never competes with the search box for attention.
    """
    rows = "".join(
        f'<div class="oprow"><span class="code">{escape(op)}</span> {escape(tr(description))}</div>'
        for op, description in _OPERATOR_HELP
    )
    return (
        '<details class="ophelp">'
        f"<summary>{escape(tr('Search operators'))}</summary>{rows}</details>"
    )


def render_home_page(
    settings_link: bool = False,
    rules: RankingRules | None = None,
    editable: bool = False,
    update_banner: tuple[str, str] | None = None,
    locale: str = "en",
) -> str:
    """The home page: a centered search box plus the OpenSearch link.

    `settings_link` adds a Settings link to the top bar; the server passes True only for the
    loopback owner, since the Settings route is owner-only. `rules` + `editable` add a scope (lens)
    selector below the search box for the loopback owner, so a scope can be chosen before searching
    (the selector renders only when at least one lens exists). `update_banner` is `(version, url)`
    for the owner-only "update available" notice (None to omit).
    """
    set_request_locale(locale)
    active_rules = rules if rules is not None else RankingRules()
    scope_select, scope_form = _home_scope(active_rules) if editable else ("", "")
    head = _page_head("SearchMob")
    body = (
        '<body data-page="home">'
        f"{_update_banner(update_banner)}"
        '<div class="topbar">'
        '<span class="logo">SearchMob</span>'
        f"{_language_select(locale)}"
        f"{_settings_link(settings_link)}"
        f"{_theme_toggle_button()}"
        "</div>"
        '<div class="home">'
        '<div class="brand">SearchMob</div>'
        f'<p class="tagline">{escape(tr("Private, on-device metasearch."))}</p>'
        '<form action="/search" method="get" class="searchbox">'
        f'<input type="text" name="q" placeholder="{escape(tr("Search the web"), quote=True)}" '
        f'aria-label="{escape(tr("Search"), quote=True)}" autocomplete="off" autofocus="autofocus">'
        f"{scope_select}"
        f'<input type="submit" value="{escape(tr("Search"), quote=True)}">'
        "</form>"
        f"{scope_form}"
        f"{_search_operators_help()}"
        "</div>"
        f"<script>{_THEME_TOGGLE_JS}</script>"
        "</body>"
    )
    return f"{_html_open(locale)}{head}{body}</html>"


def _vertical_bar(query: str, vertical: str) -> str:
    """Category tabs (Web / News / Forums / Academic) as GET links carrying the current query.

    Each link re-runs the search scoped to that vertical. The active one is marked so CSS can style
    it. Links (not a select) so the categories are visible at a glance and bookmarkable.
    """
    safe_q = quote_plus(query)
    # Literal `trc` calls (not a loop variable) so the extractor sees each label and the "search
    # category" context disambiguates these short words for translators.
    labels = {
        "web": trc("search category", "Web"),
        "news": trc("search category", "News"),
        "forums": trc("search category", "Forums"),
        "academic": trc("search category", "Academic"),
    }
    chips = []
    for value in ("web", "news", "forums", "academic"):
        is_active = value == vertical
        active = " active" if is_active else ""
        # aria-current marks the active category for assistive tech (not by color alone).
        current = ' aria-current="page"' if is_active else ""
        href = f"/search?q={safe_q}&vertical={value}"
        chips.append(
            f'<a class="chip{active}"{current} href="{escape(href, quote=True)}">'
            f"{escape(labels[value])}</a>"
        )
    nav_label = escape(tr("Search categories"), quote=True)
    return f'<nav class="verticalbar" aria-label="{nav_label}">' + "".join(chips) + "</nav>"


def _engine_status_line(engine_status: Sequence[EngineOutcome]) -> str:
    """Owner-only, unobtrusive "N of M engines responded" disclosure with per-engine detail.

    A native `<details>` element so it is keyboard-accessible with no JavaScript and not color-only:
    the summary states the count in words, the open panel lists each engine's outcome. Returns ""
    when no status is supplied (a LAN visitor, or a fake metasearch with no per-engine data), so the
    line never appears for non-owners.
    """
    if not engine_status:
        return ""
    total = len(engine_status)
    responded = sum(1 for o in engine_status if o.status != "failed")
    summary = tr("{responded} of {total} engines responded", responded=responded, total=total)
    rows: list[str] = []
    for outcome in engine_status:
        if outcome.status == "contributed":
            detail = trn(outcome.count, "{n} result", "{n} results")
        elif outcome.status == "empty":
            detail = trc("engine status", "no results")
        else:
            detail = trc("engine status", "failed")
        rows.append(
            f'<li class="engine engine-{outcome.status}">'
            f"{escape(outcome.name)} — {escape(detail)}</li>"
        )
    return (
        '<details class="engine-status meta">'
        f"<summary>{escape(summary)}</summary><ul>{''.join(rows)}</ul></details>"
    )


def _sort_bar(query: str, sort_mode: str) -> str:
    """A sort selector. GET so the choice is bookmarkable; carries the query in a hidden field."""
    # Literal `trc` calls so the extractor sees each label; "sort order" disambiguates the short
    # words (especially "Date") for translators.
    labels = {
        "fresh": trc("sort order", "Freshest + Relevant"),
        "date": trc("sort order", "Date"),
        "relevance": trc("sort order", "Relevance"),
    }
    options = []
    for value in ("fresh", "date", "relevance"):
        selected = " selected" if value == sort_mode else ""
        label_html = escape(labels[value])
        options.append(f'<option value="{value}"{selected}>{label_html}</option>')
    return (
        '<form class="scopebar" action="/search" method="get">'
        f'<input type="hidden" name="q" value="{escape(query, quote=True)}">'
        f'<label for="sm-sort">{escape(tr("Sort"))}:</label>'
        '<select id="sm-sort" name="sort" onchange="this.form.submit()">'
        + "".join(options)
        + "</select>"
        f'<noscript><button type="submit">{escape(tr("Apply"))}</button></noscript>'
        "</form>"
    )


def _short_lens_label(name: str) -> str:
    """Drop a trailing parenthetical from a lens name for the compact nested scope selector.

    "Less clutter (no Pinterest/Quora)" -> "Less clutter". The full name is kept in a hover title.
    """
    idx = name.find(" (")
    short = name[:idx].rstrip() if idx > 0 else name
    return short or name


def _home_scope(rules: RankingRules) -> tuple[str, str]:
    """The home-page scope (lens) selector, nested inside the search box.

    Returns the `<select>` (placed just left of the Search button) and a hidden `/scope` form it
    submits to via the HTML `form=` attribute, so changing the scope persists exactly as the
    standalone scope bar does without nesting two forms. Both are empty when no lens is defined.

    The visible label drops any trailing parenthetical to stay compact; the full lens name is the
    option value and a hover `title` (on both each option and the collapsed select).
    """
    if not rules.lenses:
        return "", ""
    options = [f'<option value="">{escape(tr("No scope"))}</option>']
    active_full = ""
    for lens in rules.lenses:
        selected = " selected" if lens.name == rules.active_lens else ""
        if selected:
            active_full = lens.name
        full = escape(lens.name, quote=True)
        options.append(
            f'<option value="{full}" title="{full}"{selected}>'
            f"{escape(_short_lens_label(lens.name))}</option>"
        )
    select_title = f' title="{escape(active_full, quote=True)}"' if active_full else ""
    select = (
        f'<select id="sm-scope" name="lens" form="sm-scope-form" aria-label="Search scope"'
        f'{select_title} onchange="this.form.submit()">' + "".join(options) + "</select>"
    )
    form = '<form id="sm-scope-form" action="/scope" method="post" hidden></form>'
    return select, form


def _search_context_fields(query: str, sort_mode: str, vertical: str) -> str:
    """Hidden q/sort/vertical fields so a mutation POST can return to the same results page.

    The served forms carry the current search this way rather than relying on the Referer: the
    hidden fields work regardless of the referrer policy (and did so under the old ``no-referrer``
    one), so the handler never has to reconstruct the originating page from a header.
    """
    return (
        f'<input type="hidden" name="q" value="{escape(query, quote=True)}">'
        f'<input type="hidden" name="sort" value="{escape(sort_mode, quote=True)}">'
        f'<input type="hidden" name="vertical" value="{escape(vertical, quote=True)}">'
    )


def _scope_bar(rules: RankingRules, query: str, sort_mode: str, vertical: str) -> str:
    """A scope (lens) selector. Renders only when the profile has at least one lens defined."""
    if not rules.lenses:
        return ""
    options = [f'<option value="">{escape(tr("No scope"))}</option>']
    for lens in rules.lenses:
        selected = " selected" if lens.name == rules.active_lens else ""
        options.append(
            f'<option value="{escape(lens.name, quote=True)}"{selected}>'
            f"{escape(lens.name)}</option>"
        )
    # onchange auto-submits when JS is on; the noscript button covers the JS-off case.
    return (
        '<form class="scopebar" action="/scope" method="post">'
        + _search_context_fields(query, sort_mode, vertical)
        + f'<label for="sm-scope">{escape(tr("Scope"))}:</label>'
        '<select id="sm-scope" name="lens" onchange="this.form.submit()">'
        + "".join(options)
        + "</select>"
        f'<noscript><button type="submit">{escape(tr("Apply"))}</button></noscript>'
        "</form>"
    )


def _clear_scope_link(query: str, sort_mode: str, vertical: str) -> str:
    """A one-click 'Clear scope' control: POST /scope with an empty lens, carrying the search ctx.

    Clearing the active lens and redirecting back to the same query re-runs it unfiltered, so the
    owner recovers the results an over-filtering scope hid without retyping anything.
    """
    return (
        '<form class="clearscope" action="/scope" method="post" style="display:inline">'
        + _search_context_fields(query, sort_mode, vertical)
        + '<input type="hidden" name="lens" value="">'
        + f'<button type="submit">{escape(tr("Clear scope"))}</button>'
        + "</form>"
    )


def _rank_controls(url: str, rules: RankingRules, query: str, sort_mode: str, vertical: str) -> str:
    """Per-result domain controls (block / lower / raise / pin / reset) as a single POST form."""
    domain = host_of_url(url)
    if not domain:
        return ""
    current = rules.domain_rules.get(domain)
    safe_domain = escape(domain, quote=True)
    parts = [
        '<form class="rank" action="/rules/domain" method="post">',
        _search_context_fields(query, sort_mode, vertical),
        f'<span class="state">{escape(domain)}</span>',
        f'<input type="hidden" name="domain" value="{safe_domain}">',
    ]
    for rule, label in _RANK_ACTIONS:
        on = " on" if current is rule else ""
        parts.append(
            f'<button class="btn{on}" type="submit" name="action" value="{rule.value}">'
            f"{escape(tr(label))}</button>"
        )
    # Offer a reset only when a rule is currently set, so the row stays compact otherwise.
    if current is not None:
        parts.append(
            f'<button type="submit" name="action" value="NORMAL">{escape(tr("Reset"))}</button>'
        )
    parts.append("</form>")
    return "".join(parts)


def _row_label(category: MediaCategory) -> str:
    """The localized verb for the actions row. Literal `trc` calls so the extractor sees them."""
    if category is MediaCategory.MUSIC:
        return trc("media actions", "Listen on")
    if category is MediaCategory.FILM_TV:
        return trc("media actions", "Watch on")
    if category is MediaCategory.BOOKS:
        return trc("media actions", "Read on")
    return trc("media actions", "Play on")


def _actions_row_card(row: ActionsRow) -> str:
    """A knowledge-panel-style row of canonical destinations for a resolved media entity.

    The verb label is localized; the destination names are brands (not translated). Every link is a
    locally-built search/deep URL and carries `rel=noopener noreferrer` like all result links.
    """
    links = "".join(
        f'<a href="{escape(link.url, quote=True)}" rel="noopener noreferrer">'
        f"{escape(link.label)}</a>"
        for link in row.links
    )
    return (
        '<div class="actions-row">'
        f'<span class="alabel">{escape(_row_label(row.category))}</span>{links}</div>'
    )


def _summary_box(summary: SummaryBox, is_safe_http_url: Callable[[str], bool]) -> str:
    """A knowledge-panel-style Wikipedia summary card shown above the results."""
    title_html = escape(summary.title)
    if summary.url and is_safe_http_url(summary.url):
        title_html = (
            f'<a href="{escape(summary.url, quote=True)}" rel="noopener noreferrer">'
            f"{escape(summary.title)}</a>"
        )
    parts = ['<div class="summary">']
    # The thumbnail loads from Wikimedia; it is decorative, so only render http(s) sources.
    if summary.thumbnail_url and is_safe_http_url(summary.thumbnail_url):
        parts.append(
            f'<img src="{escape(summary.thumbnail_url, quote=True)}" alt="" loading="lazy">'
        )
    parts.append('<div class="body">')
    parts.append(f'<p class="stitle">{title_html}</p>')
    if summary.description:
        parts.append(f'<p class="sdesc">{escape(summary.description)}</p>')
    parts.append(f'<p class="sextract">{escape(summary.extract)}</p>')
    parts.append(f'<p class="ssource meta">{escape(tr("From Wikipedia"))}</p>')
    parts.append("</div></div>")
    return "".join(parts)


def render_results_page(
    query: str,
    results: Iterable[SearchResult],
    is_safe_http_url: Callable[[str], bool],
    correction: str | None = None,
    rules: RankingRules | None = None,
    editable: bool = False,
    summary: SummaryBox | None = None,
    sort_mode: str = "fresh",
    vertical: str = "web",
    settings_link: bool = False,
    link_builder: Callable[[int, str], str] | None = None,
    update_banner: tuple[str, str] | None = None,
    locale: str = "en",
    # Per-engine outcome for this search, shown to the owner only (the server passes () for LAN
    # visitors). Diagnostic; never persisted or sent anywhere.
    engine_status: Sequence[EngineOutcome] = (),
    # The "Listen/Watch/Read/Play on" actions row for a resolved media entity, or None.
    actions_row: ActionsRow | None = None,
) -> str:
    """The results page. Empty/blank query -> a placeholder; otherwise -> the merged results.

    `query` must already be the length-clamped value the JSON endpoint also echoes; this renderer
    only escapes it for HTML safety. `is_safe_http_url` is the scheme-allowlist predicate so a
    `javascript:` or `data:` URL is rendered as plain text instead of an anchor.

    `correction`, when set, is a "did you mean" suggestion from the on-device corrector; it renders
    a link that re-runs the search with the corrected query.

    `rules` is the active personalization profile (used to show the current scope and per-domain
    rule states). `editable` enables the in-page controls (scope selector, per-result block/lower/
    raise/pin); the server passes it True only for the loopback owner, so a network visitor sees a
    read-only page.
    """
    set_request_locale(locale)
    active_rules = rules if rules is not None else RankingRules()
    # Materialize once so we can both branch on emptiness and iterate.
    results_list = list(results)
    blank = not query.strip()
    title_text = "SearchMob" if blank else f"{query} · SearchMob"
    head = _page_head(title_text)

    parts: list[str] = []
    parts.append('<body data-page="results">')
    parts.append(_update_banner(update_banner))
    parts.append('<div class="topbar">')
    parts.append('<a href="/" class="logo">SearchMob</a>')
    parts.append('<form action="/search" method="get" class="searchbox">')
    parts.append(
        f'<input type="text" name="q" placeholder="{escape(tr("Search the web"), quote=True)}" '
        f'aria-label="{escape(tr("Search"), quote=True)}" '
        f'value="{escape(query, quote=True)}" autocomplete="off" spellcheck="false">'
    )
    parts.append(f'<input type="submit" value="{escape(tr("Search"), quote=True)}">')
    parts.append("</form>")
    parts.append(_language_select(locale))
    parts.append(_settings_link(settings_link))
    parts.append(_theme_toggle_button())
    parts.append("</div>")
    parts.append('<div class="results">')

    # Category tabs render whenever there is a query, so the user can switch verticals even from a
    # vertical that returned nothing.
    if not blank:
        parts.append(_vertical_bar(query, vertical))

    if not blank and correction:
        href = "/search?q=" + quote_plus(correction)
        parts.append(
            f'<p class="didyoumean">{escape(tr("Did you mean:"))} '
            f'<a href="{escape(href, quote=True)}">{escape(correction)}</a></p>'
        )

    if not blank and summary is not None:
        parts.append(_summary_box(summary, is_safe_http_url))

    if not blank and actions_row is not None:
        parts.append(_actions_row_card(actions_row))

    if blank:
        parts.append(f'<p class="empty">{escape(tr("Enter a query to search."))}</p>')
    elif not results_list:
        active_lens = active_rules.active_lens
        if editable and active_lens:
            # An active scope filtered every result out. Without this the page looked empty with no
            # hint why and no way back: the scope bar only rendered when there WERE results, so the
            # owner could neither see nor clear the scope that hid them. Show both here.
            parts.append(_scope_bar(active_rules, query, sort_mode, vertical))
            parts.append('<p class="empty">')
            parts.append(
                escape(
                    tr(
                        "No results match the “{scope}” scope for “{query}”.",
                        scope=active_lens,
                        query=query,
                    )
                )
            )
            parts.append(" ")
            parts.append(_clear_scope_link(query, sort_mode, vertical))
            parts.append("</p>")
        else:
            parts.append(
                f'<p class="empty">{escape(tr("No results for “{query}”.", query=query))}</p>'
            )
    else:
        parts.append(f'<p class="meta">{escape(tr("Results for “{query}”", query=query))}</p>')
        parts.append(_engine_status_line(engine_status))
        parts.append(_sort_bar(query, sort_mode))
        if editable:
            parts.append(_scope_bar(active_rules, query, sort_mode, vertical))
        for index, result in enumerate(results_list):
            # Results past the first reveal window start collapsed; the reveal script unhides them
            # in batches on scroll. The full list is still in the DOM, so click positions (and the
            # owner's /click training links) stay aligned with the rendered order.
            collapsed = " is-collapsed" if index >= _REVEAL_SIZE else ""
            parts.append(f'<div class="result{collapsed}">')
            parts.append(f'<div class="url">{escape(_display_url(result.url))}</div>')
            if is_safe_http_url(result.url):
                # rel=noreferrer backs up the Referrer-Policy header so the query (in the loopback
                # URL) never leaks to the destination; noopener severs window.opener. When a
                # link_builder is wired (owner + personalization on), the anchor points at the
                # owner-only `/click` redirector so the click can train the model; otherwise it is
                # the plain destination URL.
                href = link_builder(index, result.url) if link_builder is not None else result.url
                parts.append(
                    f'<a href="{escape(href, quote=True)}" class="title" '
                    f'rel="noopener noreferrer">{escape(result.title)}</a>'
                )
            else:
                parts.append(f'<span class="title">{escape(result.title)}</span>')
            if result.snippet.strip():
                parts.append(f'<p class="snippet">{escape(result.snippet)}</p>')
            if result.engine.strip():
                parts.append('<div class="engines">')
                for engine in result.engine.split(","):
                    name = engine.strip()
                    if name:
                        parts.append(f'<span class="chip">{escape(name)}</span>')
                parts.append("</div>")
            if editable:
                parts.append(_rank_controls(result.url, active_rules, query, sort_mode, vertical))
            parts.append("</div>")
        if len(results_list) > _REVEAL_SIZE:
            parts.append('<div class="reveal-sentinel" aria-hidden="true"></div>')

    parts.append("</div>")
    if len(results_list) > _REVEAL_SIZE:
        parts.append(f"<script>{_REVEAL_JS}</script>")
    parts.append(f"<script>{_THEME_TOGGLE_JS}</script>")
    parts.append("</body>")
    return _html_open(locale) + head + "".join(parts) + "</html>"


def _select(name: str, options: tuple[tuple[str, str], ...], current: str) -> str:
    """A `<select>` of (value, label) pairs with `current` marked selected."""
    opts = []
    for value, label in options:
        selected = " selected" if value == current else ""
        opts.append(
            f'<option value="{escape(value, quote=True)}"{selected}>{escape(tr(label))}</option>'
        )
    return f'<select name="{escape(name, quote=True)}">' + "".join(opts) + "</select>"


def _checkbox(name: str, label: str, checked: bool) -> str:
    """A labeled checkbox. HTML omits an unchecked box from a POST; the server reads that as off."""
    on = " checked" if checked else ""
    return (
        '<label class="checkrow">'
        f'<input type="checkbox" name="{escape(name, quote=True)}" value="on"{on}> '
        f"{escape(tr(label))}</label>"
    )


_SORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fresh", N_("Freshest + Relevant")),
    ("date", N_("Date (newest first)")),
    ("relevance", N_("Relevance")),
)
_SLOP_OPTIONS: tuple[tuple[str, str], ...] = (
    ("downrank", N_("Downrank (default)")),
    ("hide", N_("Hide")),
    ("off", N_("Off")),
)


_ADD_RULE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("RAISE", N_("Raise")),
    ("LOWER", N_("Lower")),
    ("BLOCK", N_("Block")),
    ("PIN", N_("Pin")),
)


def _domain_rules_section(rules: RankingRules) -> str:
    """The Domain rules card: every saved per-domain rule (editable) plus an add form."""
    parts = [f'<section class="card"><h2>{escape(tr("Domain rules"))}</h2>']
    if rules.domain_rules:
        parts.append('<ul class="rulelist">')
        for domain, rule in sorted(rules.domain_rules.items()):
            parts.append("<li>")
            parts.append(f'<span class="dom">{escape(domain)}</span>')
            parts.append('<form class="rank" action="/rules/domain" method="post">')
            parts.append(
                f'<input type="hidden" name="domain" value="{escape(domain, quote=True)}">'
            )
            for action_rule, label in _RANK_ACTIONS:
                on = " on" if action_rule is rule else ""
                parts.append(
                    f'<button class="btn{on}" type="submit" name="action" '
                    f'value="{action_rule.value}">{escape(tr(label))}</button>'
                )
            parts.append(
                f'<button type="submit" name="action" value="NORMAL">{escape(tr("Reset"))}</button>'
            )
            parts.append("</form></li>")
        parts.append("</ul>")
    else:
        parts.append(
            f'<p class="hint">{
                escape(
                    tr(
                        "No domain rules yet. Add one below, or use the "
                        "Block / Lower / Raise / Pin buttons on any result."
                    )
                )
            }</p>'
        )
    parts.append('<form class="addrule" action="/rules/domain" method="post">')
    parts.append(
        '<input type="text" name="domain" placeholder="example.com" autocomplete="off" required>'
    )
    parts.append(_select("action", _ADD_RULE_OPTIONS, "RAISE"))
    parts.append(f'<button type="submit">{escape(tr("Add rule"))}</button>')
    parts.append("</form>")
    parts.append("</section>")
    return "".join(parts)


def _lens_form(lens: Lens | None) -> str:
    """A lens edit form prefilled from `lens`, or an empty create form when None."""
    name = lens.name if lens else ""
    fields = (
        ("include_domains", N_("Only these domains"), lens.include_domains if lens else ()),
        ("exclude_domains", N_("Exclude these domains"), lens.exclude_domains if lens else ()),
        ("include_keywords", N_("Require these keywords"), lens.include_keywords if lens else ()),
        ("exclude_keywords", N_("Exclude these keywords"), lens.exclude_keywords if lens else ()),
    )
    parts = ['<form class="lensform" action="/settings/lens" method="post">']
    name_ph = escape(tr("Scope name"), quote=True)
    parts.append(
        f'<input class="lname" type="text" name="name" placeholder="{name_ph}" '
        f'value="{escape(name, quote=True)}" autocomplete="off" required>'
    )
    placeholder = escape(tr("comma separated"), quote=True)
    for fname, label, values in fields:
        joined = ", ".join(values)
        parts.append(
            f'<label class="lf">{escape(tr(label))}'
            f'<input type="text" name="{fname}" value="{escape(joined, quote=True)}" '
            f'placeholder="{placeholder}" autocomplete="off"></label>'
        )
    parts.append(f'<button type="submit">{escape(tr("Save scope"))}</button>')
    parts.append("</form>")
    return "".join(parts)


def _lenses_section(rules: RankingRules) -> str:
    """The Scopes card: the active selector, each lens (edit + delete), and a create form."""
    parts = [f'<section class="card"><h2>{escape(tr("Scopes (lenses)"))}</h2>']
    parts.append(
        f'<p class="hint">{
            escape(
                tr(
                    "A scope filters results to the domains and keywords you "
                    "choose. Set the active scope here, or per-search from the results page."
                )
            )
        }</p>'
    )
    if rules.lenses:
        opts = [f'<option value="">{escape(tr("No scope"))}</option>']
        for lens in rules.lenses:
            sel = " selected" if lens.name == rules.active_lens else ""
            opts.append(
                f'<option value="{escape(lens.name, quote=True)}"{sel}>{escape(lens.name)}</option>'
            )
        parts.append(
            '<form class="scopebar" action="/scope" method="post">'
            f"<label>{escape(tr('Active scope'))}</label>"
        )
        parts.append(
            '<select name="lens" onchange="this.form.submit()">' + "".join(opts) + "</select>"
        )
        parts.append(
            f'<noscript><button type="submit">{escape(tr("Apply"))}</button></noscript></form>'
        )
        for lens in rules.lenses:
            parts.append('<div class="lensitem">')
            parts.append(_lens_form(lens))
            parts.append(
                '<form class="lensdel" action="/settings/lens/delete" method="post">'
                f'<input type="hidden" name="name" value="{escape(lens.name, quote=True)}">'
                f'<button type="submit">{escape(tr("Delete"))}</button></form>'
            )
            parts.append("</div>")
    parts.append(f'<h3 class="sub">{escape(tr("Create a scope"))}</h3>')
    parts.append(_lens_form(None))
    parts.append("</section>")
    return "".join(parts)


# A goggle action maps to a rank effect; show it in plain words in the goggle list.
_GOGGLE_ACTION_LABELS = {
    RankRule.BLOCK: N_("discard"),
    RankRule.RAISE: N_("boost"),
    RankRule.LOWER: N_("downrank"),
    RankRule.PIN: N_("pin"),
}

# Read a chosen .goggle file into the textarea so "upload" works without a multipart parser: the
# file never leaves the browser; its text just fills the field the normal urlencoded POST sends.
_GOGGLE_FILE_JS = (
    "function smLoadGoggle(input){var f=input.files&&input.files[0];if(!f)return;"
    "var r=new FileReader();r.onload=function(e){"
    "document.getElementById('sm-goggle-text').value=e.target.result;};r.readAsText(f);}"
)


def _goggles_section(rules: RankingRules) -> str:
    """The Goggles card: current goggle rules, a paste/upload import (append), and clear-all."""
    parts = [f'<section class="card"><h2>{escape(tr("Goggles"))}</h2>']
    parts.append(
        f'<p class="hint">{escape(tr("Brave-style goggle rules, applied on-device."))} '
        f"{escape(tr('Example:'))} <code>$discard,site=example.com</code> "
        f"{escape(tr('or'))} <code>$boost,site=dev.to</code>.</p>"
    )
    if rules.goggles:
        parts.append('<ul class="gogglelist">')
        for goggle in rules.goggles:
            action = _GOGGLE_ACTION_LABELS.get(goggle.action, goggle.action.value.lower())
            parts.append(
                f'<li><span class="site">{escape(goggle.site)}</span>'
                f'<span class="act">{escape(tr(action))}</span></li>'
            )
        parts.append("</ul>")
        clear_label = escape(trn(len(rules.goggles), "Clear all {n} rule", "Clear all {n} rules"))
        parts.append(
            '<form class="goggleclear" action="/settings/goggles/clear" method="post">'
            f'<button type="submit">{clear_label}</button></form>'
        )
    else:
        parts.append(f'<p class="hint">{escape(tr("No goggle rules imported yet."))}</p>')
    parts.append('<form class="goggleimport" action="/settings/goggles" method="post">')
    parts.append(
        '<textarea id="sm-goggle-text" name="goggles" rows="4" '
        f'placeholder="{escape(tr("Paste goggle rules, one per line"), quote=True)}"></textarea>'
    )
    parts.append(
        '<div class="grow"><input type="file" accept=".goggle,.txt,text/plain" '
        f'onchange="smLoadGoggle(this)"><button type="submit">{escape(tr("Import (append)"))}'
        "</button></div>"
    )
    parts.append("</form>")
    parts.append("</section>")
    return "".join(parts)


def _history_section(history: list[HistoryEntry] | None, clearable: bool) -> str:
    """The Search history card: recent queries and a clear-all button. Owner-only (loopback)."""
    if history is None:
        return ""
    parts = [f'<section class="card"><h2>{escape(tr("Search history"))}</h2>']
    if history:
        parts.append('<ul class="histlist">')
        for entry in history:
            parts.append(f"<li>{escape(entry.query)}</li>")
        parts.append("</ul>")
        if clearable:
            parts.append(
                '<form class="histclear" action="/settings/history/clear" method="post">'
                f'<button type="submit">{escape(tr("Clear search history"))}</button></form>'
            )
    else:
        parts.append(
            f'<p class="hint">{
                escape(tr("No search history (history is off, or nothing recorded yet)."))
            }</p>'
        )
    parts.append("</section>")
    return "".join(parts)


# The mode options for the Appearance picker. `system` follows the OS scheme; absent value (a
# never-touched picker) is treated as system by the controls JS.
_THEME_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("light", N_("Light")),
    ("dark", N_("Dark")),
    ("system", N_("Follow system")),
)


def _appearance_section() -> str:
    """The Appearance card: mode + the two slot theme pickers + an A-/A+ text-size stepper.

    All client-side (localStorage); the controls JS below wires the selects and buttons. The slot
    selects are filled from `THEMES` so the served list matches the GUI's, partitioned by mode.
    """
    mode_opts = "".join(
        f'<option value="{value}">{escape(tr(label))}</option>'
        for value, label in _THEME_MODE_OPTIONS
    )
    light_opts = "".join(
        f'<option value="{escape(t.id, quote=True)}">{escape(t.name)}</option>'
        for t in THEMES.values()
        if t.mode == LIGHT
    )
    dark_opts = "".join(
        f'<option value="{escape(t.id, quote=True)}">{escape(t.name)}</option>'
        for t in THEMES.values()
        if t.mode != LIGHT
    )
    smaller = escape(tr("Smaller text"), quote=True)
    larger = escape(tr("Larger text"), quote=True)
    return (
        f'<section class="card"><h2>{escape(tr("Appearance"))}</h2>'
        f'<div class="field"><label for="sm-mode">{escape(tr("Mode"))}</label>'
        f'<select id="sm-mode">{mode_opts}</select></div>'
        f'<div class="field"><label for="sm-light-theme">{escape(tr("Light theme"))}</label>'
        f'<select id="sm-light-theme">{light_opts}</select></div>'
        f'<div class="field"><label for="sm-dark-theme">{escape(tr("Dark theme"))}</label>'
        f'<select id="sm-dark-theme">{dark_opts}</select></div>'
        f'<div class="field"><label>{escape(tr("Text size"))}</label>'
        '<div class="sizerow">'
        f'<button type="button" id="sm-font-dec" aria-label="{smaller}">A-</button>'
        '<span class="sizeval" id="sm-font-val"></span>'
        f'<button type="button" id="sm-font-inc" aria-label="{larger}">A+</button>'
        "</div></div>"
        "</section>"
    )


# Wires the Appearance card to localStorage (settings page only). On load it sets each control to
# its stored value; on change it persists and live-applies via the shared resolve helpers. Font is
# clamped to the 8..24/step-2 bounds. No server round-trip: served prefs have always been local.
_THEME_CONTROLS_JS = (
    "(function(){"
    + _THEME_RESOLVE_JS
    + f"var MIN={_JS_MIN_FONT},MAX={_JS_MAX_FONT},STEP={_JS_STEP_FONT},DEF=12;"
    "function font(){var f=parseInt(smGet('sm-font'),10);"
    "return isNaN(f)?DEF:Math.max(MIN,Math.min(MAX,f));}"
    "function set(k,v){try{localStorage.setItem(k,v);}catch(e){}}"
    "var mode=document.getElementById('sm-mode');"
    "var li=document.getElementById('sm-light-theme');"
    "var di=document.getElementById('sm-dark-theme');"
    "var val=document.getElementById('sm-font-val');"
    "var dec=document.getElementById('sm-font-dec');"
    "var inc=document.getElementById('sm-font-inc');"
    "function showFont(){if(val)val.textContent=font()+' pt';}"
    "var s=smSlots();"
    "if(mode)mode.value=smGet('sm-theme')||'system';"
    "if(li)li.value=s.light;if(di)di.value=s.dark;"
    "showFont();"
    "if(mode)mode.addEventListener('change',function(){set('sm-theme',mode.value);smApply();});"
    "if(li)li.addEventListener('change',function(){set('sm-light-theme',li.value);smApply();});"
    "if(di)di.addEventListener('change',function(){set('sm-dark-theme',di.value);smApply();});"
    "function step(d){var n=Math.max(MIN,Math.min(MAX,font()+d*STEP));"
    "set('sm-font',n);smApply();showFont();}"
    "if(dec)dec.addEventListener('click',function(){step(-1);});"
    "if(inc)inc.addEventListener('click',function(){step(1);});"
    "})();"
)


def render_settings_page(
    prefs: UserPreferences,
    rules: RankingRules,
    saved: bool = False,
    history: list[HistoryEntry] | None = None,
    history_clearable: bool = False,
    locale: str = "en",
) -> str:
    """The browser Settings page: live preference toggles plus domain-rule and scope management.

    Owner-only (the server serves it to a loopback client and 404s otherwise). `saved` shows a brief
    confirmation after a successful POST. Mirrors the relevant parts of the desktop Settings dialog:
    the preference toggles map to `UserPreferences` fields; `rules` drives the domain-rule list, the
    scope (lens) editor, and the goggles list (all persisted to the encrypted ranking store); and
    `history`, when provided, shows recent queries with a clear-all button (`history_clearable`).
    Passing `history=None` omits the history card entirely.
    """
    set_request_locale(locale)
    head = _page_head(tr("Settings") + " · SearchMob")
    parts: list[str] = []
    parts.append('<body data-page="settings">')
    parts.append('<div class="topbar">')
    parts.append('<a href="/" class="logo">SearchMob</a>')
    parts.append('<span class="spacer"></span>')
    parts.append(_language_select(locale))
    parts.append(_theme_toggle_button())
    parts.append("</div>")
    parts.append('<div class="settings">')
    parts.append(f"<h1>{escape(tr('Settings'))}</h1>")
    if saved:
        parts.append(f'<p class="saved" role="status">{escape(tr("Saved."))}</p>')

    # The Appearance card is client-side only (localStorage), so it sits above the prefs form rather
    # than inside it; nothing here posts to the server.
    parts.append(_appearance_section())

    parts.append('<form action="/settings/prefs" method="post">')

    parts.append('<section class="card">')
    parts.append(f"<h2>{escape(tr('Search & ranking'))}</h2>")
    parts.append(f'<div class="field"><label>{escape(tr("Default sort"))}</label>')
    parts.append(_select("sort_mode", _SORT_OPTIONS, prefs.sort_mode))
    parts.append("</div>")
    parts.append(f'<div class="field"><label>{escape(tr("AI-slop / low-quality filter"))}</label>')
    parts.append(_select("ai_slop_mode", _SLOP_OPTIONS, prefs.ai_slop_mode))
    parts.append(
        f'<p class="hint">{
            escape(tr("Applied on-device after your own domain rules, which always win."))
        }</p>'
    )
    parts.append("</div>")
    parts.append("</section>")

    parts.append('<section class="card">')
    parts.append(f"<h2>{escape(tr('Suggestions'))}</h2>")
    parts.append(
        _checkbox("summary_enabled", N_("Show the Wikipedia summary card"), prefs.summary_enabled)
    )
    parts.append(
        _checkbox(
            "media_actions_enabled",
            N_("Show media links (films, music, books, games)"),
            prefs.media_actions_enabled,
        )
    )
    parts.append(
        _checkbox(
            "upstream_suggestions_enabled",
            N_("Use upstream autocomplete suggestions"),
            prefs.upstream_suggestions_enabled,
        )
    )
    parts.append(
        f'<p class="hint">{
            escape(
                tr(
                    "Upstream autocomplete sends what you type to a suggestions "
                    "service; your on-device history suggestions are always private."
                )
            )
        }</p>'
    )
    parts.append("</section>")

    parts.append(f'<div class="actions"><button type="submit">{escape(tr("Save"))}</button></div>')
    parts.append("</form>")

    # Domain rules, scopes, goggles, and history are their own forms (each posts independently), so
    # they live outside the preferences form above.
    parts.append(_domain_rules_section(rules))
    parts.append(_lenses_section(rules))
    parts.append(_goggles_section(rules))
    parts.append(_history_section(history, history_clearable))

    parts.append("</div>")
    parts.append(f"<script>{_THEME_TOGGLE_JS}</script>")
    parts.append(f"<script>{_THEME_CONTROLS_JS}</script>")
    parts.append(f"<script>{_GOGGLE_FILE_JS}</script>")
    parts.append("</body>")
    return _html_open(locale) + head + "".join(parts) + "</html>"

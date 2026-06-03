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

from collections.abc import Callable, Iterable
from html import escape
from urllib.parse import quote_plus, urlsplit

from searchmob_desktop.data.history import HistoryEntry
from searchmob_desktop.engines import SearchResult
from searchmob_desktop.engines.rank import Lens, RankingRules, RankRule, host_of_url
from searchmob_desktop.engines.wiki_summary import SummaryBox
from searchmob_desktop.prefs import UserPreferences

# The per-result domain actions offered in the served UI, in display order. Mirrors the in-app
# right-click menu (block / lower / raise / pin); "Reset" maps to NORMAL (removes the rule).
_RANK_ACTIONS: tuple[tuple[RankRule, str], ...] = (
    (RankRule.BLOCK, "Block"),
    (RankRule.LOWER, "Lower"),
    (RankRule.RAISE, "Raise"),
    (RankRule.PIN, "Pin"),
)

# Self-contained stylesheet: no external fonts / CDNs / runtime fetches. Light defaults plus a
# `prefers-color-scheme: dark` media query; a `[data-theme]` attribute on the root overrides both
# so the JS toggle is authoritative. Kept tight on whitespace to keep the served bytes small.
_PAGE_CSS = (
    "*{box-sizing:border-box}"
    "html,body{margin:0;padding:0}"
    ":root{"
    "--bg:#ffffff;--fg:#202124;--muted:#5f6368;--border:#dfe1e5;--card:#ffffff;"
    "--link:#1a0dab;--url:#0b8043;--snippet:#4d5156;--chip-bg:#f1f3f4;--chip-fg:#5f6368;"
    "--accent:#3d5afe;--shadow:0 1px 6px rgba(32,33,36,.12);--topbar:#ffffffee;"
    "}"
    "@media (prefers-color-scheme:dark){:root{"
    "--bg:#0e0f13;--fg:#e3e5e8;--muted:#9aa0a6;--border:#2a2c33;--card:#15171c;"
    "--link:#8ab4f8;--url:#5fd07f;--snippet:#bdc1c6;--chip-bg:#1f2127;--chip-fg:#c5c8ce;"
    "--accent:#8c9eff;--shadow:0 1px 6px rgba(0,0,0,.5);--topbar:#0e0f13ee;"
    "}}"
    '[data-theme="light"]{'
    "--bg:#ffffff;--fg:#202124;--muted:#5f6368;--border:#dfe1e5;--card:#ffffff;"
    "--link:#1a0dab;--url:#0b8043;--snippet:#4d5156;--chip-bg:#f1f3f4;--chip-fg:#5f6368;"
    "--accent:#3d5afe;--shadow:0 1px 6px rgba(32,33,36,.12);--topbar:#ffffffee;"
    "}"
    '[data-theme="dark"]{'
    "--bg:#0e0f13;--fg:#e3e5e8;--muted:#9aa0a6;--border:#2a2c33;--card:#15171c;"
    "--link:#8ab4f8;--url:#5fd07f;--snippet:#bdc1c6;--chip-bg:#1f2127;--chip-fg:#c5c8ce;"
    "--accent:#8c9eff;--shadow:0 1px 6px rgba(0,0,0,.5);--topbar:#0e0f13ee;"
    "}"
    "body{background:var(--bg);color:var(--fg);line-height:1.5;"
    'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}'
    "a{color:var(--link);text-decoration:none}"
    "a:hover{text-decoration:underline}"
    ".topbar{display:flex;align-items:center;gap:14px;padding:10px 18px;"
    "border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--topbar);"
    "backdrop-filter:saturate(1.4) blur(8px);z-index:10}"
    ".topbar .logo{font-weight:800;font-size:20px;color:var(--accent);letter-spacing:-.5px;"
    "white-space:nowrap}"
    ".theme-toggle{margin-left:auto;background:transparent;border:1px solid var(--border);"
    "color:var(--fg);border-radius:20px;padding:6px 14px;cursor:pointer;font-size:13px;"
    "white-space:nowrap}"
    ".theme-toggle:hover{border-color:var(--accent);color:var(--accent)}"
    ".settings-link{margin-left:auto;border:1px solid var(--border);color:var(--fg);"
    "border-radius:20px;padding:6px 14px;font-size:13px;text-decoration:none;white-space:nowrap}"
    ".settings-link:hover{border-color:var(--accent);color:var(--accent)}"
    ".settings-link+.theme-toggle{margin-left:0}"
    ".topbar .spacer{margin-left:auto}"
    # Owner-only "update available" banner, pinned above the top bar. Accent fill so it reads as a
    # notice without an icon set; the action is a high-contrast pill linking to the release.
    ".updatebar{display:flex;align-items:center;gap:12px;padding:9px 18px;background:var(--accent);"
    "color:#fff;font-size:13px}"
    ".updatebar .msg{font-weight:600}"
    ".updatebar .btn{margin-left:auto;background:#fff;color:var(--accent);border-radius:16px;"
    "padding:5px 14px;font-weight:700;text-decoration:none;white-space:nowrap}"
    ".updatebar .btn:hover{text-decoration:none;opacity:.92}"
    ".settings{max-width:680px;margin:0 auto;padding:24px 18px 60px}"
    ".settings h1{font-size:24px;margin:8px 0 18px}"
    ".settings .saved{color:#fff;background:var(--accent);display:inline-block;border-radius:6px;"
    "padding:4px 12px;font-size:13px;margin:0 0 16px}"
    ".settings .card{background:var(--card);border:1px solid var(--border);border-radius:12px;"
    "padding:16px 18px;margin:0 0 16px}"
    ".settings .card h2{font-size:15px;margin:0 0 14px;color:var(--accent)}"
    ".settings .field{margin:0 0 14px}"
    ".settings .field>label{display:block;font-size:13px;margin:0 0 6px;font-weight:600}"
    ".settings select{width:100%;padding:9px 12px;border:1px solid var(--border);border-radius:8px;"
    "background:var(--bg);color:var(--fg);font-size:14px}"
    ".settings .checkrow{display:flex;align-items:center;gap:9px;font-size:14px;margin:0 0 10px;"
    "cursor:pointer}"
    ".settings .hint{font-size:12px;color:var(--muted);margin:6px 0 0}"
    ".settings .actions{margin-top:6px}"
    ".settings .actions button{background:var(--accent);color:#fff;border:0;border-radius:22px;"
    "padding:10px 26px;font-size:15px;font-weight:600;cursor:pointer}"
    ".settings .card h3.sub{font-size:13px;margin:16px 0 8px;color:var(--muted)}"
    ".settings .rulelist{list-style:none;margin:0 0 14px;padding:0}"
    ".settings .rulelist li{display:flex;align-items:center;gap:8px;flex-wrap:wrap;"
    "padding:8px 0;border-bottom:1px solid var(--border)}"
    ".settings .rulelist .dom{font-weight:600;font-size:13px;word-break:break-all}"
    ".settings .rulelist .rank{margin-left:auto}"
    ".settings .addrule{display:flex;gap:8px;flex-wrap:wrap;align-items:center}"
    ".settings .addrule input[type=text]{flex:1;min-width:140px;padding:8px 11px;"
    "border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--fg);"
    "font-size:14px}"
    ".settings .addrule select{width:auto;min-width:110px}"
    ".settings .addrule button,.settings .lensform button,.settings .lensdel button{"
    "background:var(--accent);color:#fff;border:0;border-radius:18px;padding:8px 18px;"
    "font-size:13px;font-weight:600;cursor:pointer}"
    ".settings .lensitem{display:flex;gap:10px;align-items:flex-start;padding:10px 0;"
    "border-bottom:1px solid var(--border)}"
    ".settings .lensform{flex:1;display:flex;flex-direction:column;gap:8px}"
    ".settings .lensform .lname{font-weight:600}"
    ".settings .lensform input[type=text]{width:100%;padding:8px 11px;"
    "border:1px solid var(--border);"
    "border-radius:8px;background:var(--bg);color:var(--fg);font-size:14px}"
    ".settings .lensform .lf{display:flex;flex-direction:column;gap:3px;font-size:12px;"
    "color:var(--muted)}"
    ".settings .lensform button{align-self:flex-start}"
    ".settings .lensdel button{background:transparent;color:var(--muted);"
    "border:1px solid var(--border)}"
    ".settings .lensdel button:hover{border-color:#d33;color:#d33}"
    ".settings .hint code{background:var(--chip-bg);color:var(--chip-fg);padding:1px 5px;"
    "border-radius:5px;font-size:12px}"
    ".settings .gogglelist,.settings .histlist{list-style:none;margin:0 0 12px;padding:0;"
    "font-size:13px}"
    ".settings .gogglelist li{display:flex;gap:8px;align-items:center;padding:5px 0;"
    "border-bottom:1px solid var(--border)}"
    ".settings .gogglelist .site{font-weight:600;word-break:break-all}"
    ".settings .gogglelist .act{margin-left:auto;font-size:11px;color:var(--muted)}"
    ".settings .histlist li{padding:4px 0;border-bottom:1px solid var(--border);"
    "word-break:break-word}"
    ".settings .goggleimport{display:flex;flex-direction:column;gap:8px}"
    ".settings textarea{width:100%;padding:9px 11px;border:1px solid var(--border);"
    "border-radius:8px;"
    "background:var(--bg);color:var(--fg);font-size:13px;font-family:ui-monospace,monospace;"
    "resize:vertical}"
    ".settings .goggleimport .grow{display:flex;gap:10px;align-items:center;flex-wrap:wrap}"
    ".settings .goggleimport button,.settings .goggleclear button,.settings .histclear button{"
    "background:var(--accent);color:#fff;border:0;border-radius:18px;padding:8px 18px;"
    "font-size:13px;"
    "font-weight:600;cursor:pointer}"
    ".settings .goggleclear button,.settings .histclear button{background:transparent;"
    "color:var(--muted);border:1px solid var(--border)}"
    ".settings .goggleclear button:hover,.settings .histclear button:hover{"
    "border-color:#d33;color:#d33}"
    ".settings .goggleclear,.settings .histclear{margin:0 0 8px}"
    ".searchbox{display:flex;align-items:stretch;background:var(--card);"
    "border:1px solid var(--border);border-radius:26px;box-shadow:var(--shadow);overflow:hidden}"
    ".searchbox input[type=text]{flex:1;min-width:0;border:0;outline:0;background:transparent;"
    "color:var(--fg);font-size:16px;padding:13px 18px}"
    ".searchbox input[type=submit]{border:0;background:var(--accent);color:#fff;padding:0 22px;"
    "cursor:pointer;font-size:15px;font-weight:600}"
    ".searchbox input[type=submit]:hover{filter:brightness(1.07)}"
    ".home{max-width:600px;margin:0 auto;padding:13vh 20px 0;text-align:center}"
    ".home .brand{font-size:48px;font-weight:800;color:var(--accent);letter-spacing:-1.5px}"
    ".home .tagline{color:var(--muted);margin:8px 0 28px;font-size:15px}"
    ".home .searchbox{max-width:560px;margin:0 auto;text-align:left}"
    ".topbar .searchbox{flex:1;max-width:620px}"
    ".topbar .searchbox input[type=text]{padding:9px 16px}"
    ".topbar .searchbox input[type=submit]{padding:0 16px}"
    ".results{max-width:660px;margin:0 auto;padding:18px 20px 64px}"
    ".results .meta{color:var(--muted);font-size:13px;margin:2px 0 20px}"
    ".didyoumean{font-size:15px;margin:2px 0 18px}"
    ".didyoumean a{font-weight:600;font-style:italic}"
    ".result{margin:0 0 26px}"
    ".result .url{color:var(--url);font-size:13px;white-space:nowrap;overflow:hidden;"
    "text-overflow:ellipsis}"
    ".result .title{display:block;font-size:20px;line-height:1.3;margin:1px 0 3px}"
    ".result .snippet{margin:2px 0 7px;color:var(--snippet);font-size:14px}"
    ".engines{display:flex;flex-wrap:wrap;gap:6px}"
    ".chip{background:var(--chip-bg);color:var(--chip-fg);font-size:11px;padding:2px 9px;"
    "border-radius:10px}"
    ".empty{color:var(--muted);text-align:center;padding:48px 0}"
    ".summary{display:flex;gap:14px;border:1px solid var(--border);border-radius:12px;"
    "background:var(--card);padding:14px 16px;margin:0 0 22px;box-shadow:var(--shadow)}"
    ".summary .body{flex:1;min-width:0}"
    ".summary .stitle{font-size:17px;font-weight:600;margin:0}"
    ".summary .stitle a{color:var(--fg)}"
    ".summary .sdesc{color:var(--muted);font-size:12px;margin:1px 0 6px}"
    ".summary .sextract{font-size:14px;margin:0 0 6px;line-height:1.45}"
    ".summary .ssource{font-size:12px}"
    ".summary img{width:84px;height:84px;object-fit:cover;border-radius:8px;flex:none}"
    "@media (max-width:560px){.summary img{display:none}}"
    ".verticalbar{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}"
    ".verticalbar .chip{font-size:13px;padding:5px 14px;border:1px solid var(--border);"
    "border-radius:16px;background:var(--card);color:var(--muted);text-decoration:none}"
    # Active chip: a fixed dark-on-light-indigo pairing (>7:1 in both themes), since white-on-accent
    # failed contrast in dark mode. aria-current also marks it, so the state is never color-only.
    ".verticalbar .chip.active{background:#c7d0ff;border-color:#c7d0ff;color:#0a1a5c;"
    "font-weight:600}"
    # Visible keyboard focus (the search input clears the default ring) + reduced-motion support.
    "a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{"
    "outline:2px solid var(--accent);outline-offset:2px}"
    "@media(prefers-reduced-motion:reduce){.topbar{backdrop-filter:none}"
    "*{animation-duration:.01ms!important;transition-duration:.01ms!important}}"
    ".scopebar{display:flex;align-items:center;gap:8px;margin:0 0 18px;font-size:13px;"
    "color:var(--muted)}"
    ".scopebar select{font-size:13px;padding:3px 6px;border:1px solid var(--border);"
    "border-radius:6px;background:var(--card);color:var(--fg)}"
    ".rank{display:flex;flex-wrap:wrap;gap:6px;margin-top:5px;align-items:center}"
    ".rank form{display:inline;margin:0}"
    ".rank .state{font-size:11px;color:var(--muted);margin-right:2px}"
    ".rank button{font-size:11px;padding:2px 9px;border:1px solid var(--border);border-radius:10px;"
    "background:var(--card);color:var(--muted);cursor:pointer}"
    ".rank button:hover{border-color:var(--accent);color:var(--fg)}"
    ".rank button.on{background:var(--accent);color:#fff;border-color:var(--accent)}"
    "@media (max-width:560px){.topbar .logo{display:none}}"
)

# Runs in <head> before first paint to restore the saved theme (avoids the flash of wrong theme).
_THEME_INIT_JS = (
    "(function(){try{var t=localStorage.getItem('sm-theme');"
    "if(t){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();"
)

# Defines smToggle() (flips + persists the theme) and labels the button with the alternative theme.
_THEME_TOGGLE_JS = (
    "(function(){"
    "function resolved(){var d=document.documentElement.getAttribute('data-theme');if(d)return d;"
    "return (window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)?"
    "'dark':'light';}"
    "function label(){var b=document.getElementById('sm-theme-btn');"
    "if(b)b.textContent=resolved()==='dark'?'\\u2600 Light':'\\u263e Dark';}"
    "window.smToggle=function(){var n=resolved()==='dark'?'light':'dark';"
    "document.documentElement.setAttribute('data-theme',n);"
    "try{localStorage.setItem('sm-theme',n);}catch(e){}label();};"
    "label();"
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
        f"<style>{_PAGE_CSS}</style>"
        f"<script>{_THEME_INIT_JS}</script>"
        "</head>"
    )


def _theme_toggle_button() -> str:
    """The light/dark toggle button. JS labels it to show the alternative theme."""
    return (
        '<button type="button" class="theme-toggle" id="sm-theme-btn" '
        'onclick="smToggle()" aria-label="Toggle light/dark theme">Theme</button>'
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
    return (
        '<div class="updatebar" role="status">'
        f'<span class="msg">SearchMob {escape(version)} is available.</span>'
        f'<a class="btn" href="{escape(url, quote=True)}" rel="noopener noreferrer">'
        "Get the update</a>"
        "</div>"
    )


def _settings_link(show: bool) -> str:
    """A Settings-page link, shown only to the loopback owner (the route itself is owner-only)."""
    if not show:
        return ""
    return '<a href="/settings" class="settings-link" aria-label="Settings">Settings</a>'


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


def render_home_page(
    settings_link: bool = False,
    rules: RankingRules | None = None,
    editable: bool = False,
    update_banner: tuple[str, str] | None = None,
) -> str:
    """The home page: a centered search box plus the OpenSearch link.

    `settings_link` adds a Settings link to the top bar; the server passes True only for the
    loopback owner, since the Settings route is owner-only. `rules` + `editable` add a scope (lens)
    selector below the search box for the loopback owner, so a scope can be chosen before searching
    (the selector renders only when at least one lens exists). `update_banner` is `(version, url)`
    for the owner-only "update available" notice (None to omit).
    """
    active_rules = rules if rules is not None else RankingRules()
    scope = _scope_bar(active_rules) if editable else ""
    head = _page_head("SearchMob")
    body = (
        '<body data-page="home">'
        f"{_update_banner(update_banner)}"
        '<div class="topbar">'
        '<span class="logo">SearchMob</span>'
        f"{_settings_link(settings_link)}"
        f"{_theme_toggle_button()}"
        "</div>"
        '<div class="home">'
        '<div class="brand">SearchMob</div>'
        '<p class="tagline">Private, on-device metasearch.</p>'
        '<form action="/search" method="get" class="searchbox">'
        '<input type="text" name="q" placeholder="Search the web" aria-label="Search" '
        'autocomplete="off" autofocus="autofocus">'
        '<input type="submit" value="Search">'
        "</form>"
        f"{scope}"
        "</div>"
        f"<script>{_THEME_TOGGLE_JS}</script>"
        "</body>"
    )
    return f"<!DOCTYPE html><html lang='en'>{head}{body}</html>"


def _vertical_bar(query: str, vertical: str) -> str:
    """Category tabs (Web / News / Forums / Academic) as GET links carrying the current query.

    Each link re-runs the search scoped to that vertical. The active one is marked so CSS can style
    it. Links (not a select) so the categories are visible at a glance and bookmarkable.
    """
    safe_q = quote_plus(query)
    chips = []
    for value, label in (
        ("web", "Web"),
        ("news", "News"),
        ("forums", "Forums"),
        ("academic", "Academic"),
    ):
        is_active = value == vertical
        active = " active" if is_active else ""
        # aria-current marks the active category for assistive tech (not by color alone).
        current = ' aria-current="page"' if is_active else ""
        href = f"/search?q={safe_q}&vertical={value}"
        chips.append(
            f'<a class="chip{active}"{current} href="{escape(href, quote=True)}">{label}</a>'
        )
    return '<nav class="verticalbar" aria-label="Search categories">' + "".join(chips) + "</nav>"


def _sort_bar(query: str, sort_mode: str) -> str:
    """A sort selector. GET so the choice is bookmarkable; carries the query in a hidden field."""
    options = []
    for value, label in (
        ("fresh", "Freshest + Relevant"),
        ("date", "Date"),
        ("relevance", "Relevance"),
    ):
        selected = " selected" if value == sort_mode else ""
        options.append(f'<option value="{value}"{selected}>{label}</option>')
    return (
        '<form class="scopebar" action="/search" method="get">'
        f'<input type="hidden" name="q" value="{escape(query, quote=True)}">'
        '<label for="sm-sort">Sort:</label>'
        '<select id="sm-sort" name="sort" onchange="this.form.submit()">'
        + "".join(options)
        + "</select>"
        '<noscript><button type="submit">Apply</button></noscript>'
        "</form>"
    )


def _scope_bar(rules: RankingRules) -> str:
    """A scope (lens) selector. Renders only when the profile has at least one lens defined."""
    if not rules.lenses:
        return ""
    options = ['<option value="">No scope</option>']
    for lens in rules.lenses:
        selected = " selected" if lens.name == rules.active_lens else ""
        options.append(
            f'<option value="{escape(lens.name, quote=True)}"{selected}>'
            f"{escape(lens.name)}</option>"
        )
    # onchange auto-submits when JS is on; the noscript button covers the JS-off case.
    return (
        '<form class="scopebar" action="/scope" method="post">'
        '<label for="sm-scope">Scope:</label>'
        '<select id="sm-scope" name="lens" onchange="this.form.submit()">'
        + "".join(options)
        + "</select>"
        '<noscript><button type="submit">Apply</button></noscript>'
        "</form>"
    )


def _rank_controls(url: str, rules: RankingRules) -> str:
    """Per-result domain controls (block / lower / raise / pin / reset) as a single POST form."""
    domain = host_of_url(url)
    if not domain:
        return ""
    current = rules.domain_rules.get(domain)
    safe_domain = escape(domain, quote=True)
    parts = [
        '<form class="rank" action="/rules/domain" method="post">',
        f'<span class="state">{escape(domain)}</span>',
        f'<input type="hidden" name="domain" value="{safe_domain}">',
    ]
    for rule, label in _RANK_ACTIONS:
        on = " on" if current is rule else ""
        parts.append(
            f'<button class="btn{on}" type="submit" name="action" value="{rule.value}">'
            f"{label}</button>"
        )
    # Offer a reset only when a rule is currently set, so the row stays compact otherwise.
    if current is not None:
        parts.append('<button type="submit" name="action" value="NORMAL">Reset</button>')
    parts.append("</form>")
    return "".join(parts)


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
    parts.append('<p class="ssource meta">From Wikipedia</p>')
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
    active_rules = rules if rules is not None else RankingRules()
    # Materialize once so we can both branch on emptiness and iterate.
    results_list = list(results)
    blank = not query.strip()
    safe_query = escape(query)
    title_text = "SearchMob" if blank else f"{query} · SearchMob"
    head = _page_head(title_text)

    parts: list[str] = []
    parts.append('<body data-page="results">')
    parts.append(_update_banner(update_banner))
    parts.append('<div class="topbar">')
    parts.append('<a href="/" class="logo">SearchMob</a>')
    parts.append('<form action="/search" method="get" class="searchbox">')
    parts.append(
        '<input type="text" name="q" placeholder="Search the web" aria-label="Search" '
        f'value="{escape(query, quote=True)}" autocomplete="off" spellcheck="false">'
    )
    parts.append('<input type="submit" value="Search">')
    parts.append("</form>")
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
            '<p class="didyoumean">Did you mean: '
            f'<a href="{escape(href, quote=True)}">{escape(correction)}</a></p>'
        )

    if not blank and summary is not None:
        parts.append(_summary_box(summary, is_safe_http_url))

    if blank:
        parts.append('<p class="empty">Enter a query to search.</p>')
    elif not results_list:
        parts.append(f'<p class="empty">No results for “{safe_query}”.</p>')
    else:
        parts.append(f'<p class="meta">Results for “{safe_query}”</p>')
        parts.append(_sort_bar(query, sort_mode))
        if editable:
            parts.append(_scope_bar(active_rules))
        for index, result in enumerate(results_list):
            parts.append('<div class="result">')
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
                parts.append(_rank_controls(result.url, active_rules))
            parts.append("</div>")

    parts.append("</div>")
    parts.append(f"<script>{_THEME_TOGGLE_JS}</script>")
    parts.append("</body>")
    return "<!DOCTYPE html><html lang='en'>" + head + "".join(parts) + "</html>"


def _select(name: str, options: tuple[tuple[str, str], ...], current: str) -> str:
    """A `<select>` of (value, label) pairs with `current` marked selected."""
    opts = []
    for value, label in options:
        selected = " selected" if value == current else ""
        opts.append(
            f'<option value="{escape(value, quote=True)}"{selected}>{escape(label)}</option>'
        )
    return f'<select name="{escape(name, quote=True)}">' + "".join(opts) + "</select>"


def _checkbox(name: str, label: str, checked: bool) -> str:
    """A labeled checkbox. HTML omits an unchecked box from a POST; the server reads that as off."""
    on = " checked" if checked else ""
    return (
        '<label class="checkrow">'
        f'<input type="checkbox" name="{escape(name, quote=True)}" value="on"{on}> {escape(label)}'
        "</label>"
    )


_SORT_OPTIONS: tuple[tuple[str, str], ...] = (
    ("fresh", "Freshest + Relevant"),
    ("date", "Date (newest first)"),
    ("relevance", "Relevance"),
)
_SLOP_OPTIONS: tuple[tuple[str, str], ...] = (
    ("downrank", "Downrank (default)"),
    ("hide", "Hide"),
    ("off", "Off"),
)


_ADD_RULE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("RAISE", "Raise"),
    ("LOWER", "Lower"),
    ("BLOCK", "Block"),
    ("PIN", "Pin"),
)


def _domain_rules_section(rules: RankingRules) -> str:
    """The Domain rules card: every saved per-domain rule (editable) plus an add form."""
    parts = ['<section class="card"><h2>Domain rules</h2>']
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
                    f'value="{action_rule.value}">{label}</button>'
                )
            parts.append('<button type="submit" name="action" value="NORMAL">Reset</button>')
            parts.append("</form></li>")
        parts.append("</ul>")
    else:
        parts.append(
            '<p class="hint">No domain rules yet. Add one below, or use the '
            "Block / Lower / Raise / Pin buttons on any result.</p>"
        )
    parts.append('<form class="addrule" action="/rules/domain" method="post">')
    parts.append(
        '<input type="text" name="domain" placeholder="example.com" autocomplete="off" required>'
    )
    parts.append(_select("action", _ADD_RULE_OPTIONS, "RAISE"))
    parts.append('<button type="submit">Add rule</button>')
    parts.append("</form>")
    parts.append("</section>")
    return "".join(parts)


def _lens_form(lens: Lens | None) -> str:
    """A lens edit form prefilled from `lens`, or an empty create form when None."""
    name = lens.name if lens else ""
    fields = (
        ("include_domains", "Only these domains", lens.include_domains if lens else ()),
        ("exclude_domains", "Exclude these domains", lens.exclude_domains if lens else ()),
        ("include_keywords", "Require these keywords", lens.include_keywords if lens else ()),
        ("exclude_keywords", "Exclude these keywords", lens.exclude_keywords if lens else ()),
    )
    parts = ['<form class="lensform" action="/settings/lens" method="post">']
    parts.append(
        '<input class="lname" type="text" name="name" placeholder="Scope name" '
        f'value="{escape(name, quote=True)}" autocomplete="off" required>'
    )
    for fname, label, values in fields:
        joined = ", ".join(values)
        parts.append(
            f'<label class="lf">{escape(label)}'
            f'<input type="text" name="{fname}" value="{escape(joined, quote=True)}" '
            'placeholder="comma separated" autocomplete="off"></label>'
        )
    parts.append('<button type="submit">Save scope</button>')
    parts.append("</form>")
    return "".join(parts)


def _lenses_section(rules: RankingRules) -> str:
    """The Scopes card: the active selector, each lens (edit + delete), and a create form."""
    parts = ['<section class="card"><h2>Scopes (lenses)</h2>']
    parts.append(
        '<p class="hint">A scope filters results to the domains and keywords you choose. '
        "Set the active scope here, or per-search from the results page.</p>"
    )
    if rules.lenses:
        opts = ['<option value="">No scope</option>']
        for lens in rules.lenses:
            sel = " selected" if lens.name == rules.active_lens else ""
            opts.append(
                f'<option value="{escape(lens.name, quote=True)}"{sel}>{escape(lens.name)}</option>'
            )
        parts.append(
            '<form class="scopebar" action="/scope" method="post"><label>Active scope</label>'
        )
        parts.append(
            '<select name="lens" onchange="this.form.submit()">' + "".join(opts) + "</select>"
        )
        parts.append('<noscript><button type="submit">Apply</button></noscript></form>')
        for lens in rules.lenses:
            parts.append('<div class="lensitem">')
            parts.append(_lens_form(lens))
            parts.append(
                '<form class="lensdel" action="/settings/lens/delete" method="post">'
                f'<input type="hidden" name="name" value="{escape(lens.name, quote=True)}">'
                '<button type="submit">Delete</button></form>'
            )
            parts.append("</div>")
    parts.append('<h3 class="sub">Create a scope</h3>')
    parts.append(_lens_form(None))
    parts.append("</section>")
    return "".join(parts)


# A goggle action maps to a rank effect; show it in plain words in the goggle list.
_GOGGLE_ACTION_LABELS = {
    RankRule.BLOCK: "discard",
    RankRule.RAISE: "boost",
    RankRule.LOWER: "downrank",
    RankRule.PIN: "pin",
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
    parts = ['<section class="card"><h2>Goggles</h2>']
    parts.append(
        '<p class="hint">Brave-style goggle rules, applied on-device. '
        "Example: <code>$discard,site=example.com</code> or <code>$boost,site=dev.to</code>.</p>"
    )
    if rules.goggles:
        parts.append('<ul class="gogglelist">')
        for goggle in rules.goggles:
            action = _GOGGLE_ACTION_LABELS.get(goggle.action, goggle.action.value.lower())
            parts.append(
                f'<li><span class="site">{escape(goggle.site)}</span>'
                f'<span class="act">{escape(action)}</span></li>'
            )
        parts.append("</ul>")
        parts.append(
            '<form class="goggleclear" action="/settings/goggles/clear" method="post">'
            f'<button type="submit">Clear all {len(rules.goggles)} rules</button></form>'
        )
    else:
        parts.append('<p class="hint">No goggle rules imported yet.</p>')
    parts.append('<form class="goggleimport" action="/settings/goggles" method="post">')
    parts.append(
        '<textarea id="sm-goggle-text" name="goggles" rows="4" '
        'placeholder="Paste goggle rules, one per line"></textarea>'
    )
    parts.append(
        '<div class="grow"><input type="file" accept=".goggle,.txt,text/plain" '
        'onchange="smLoadGoggle(this)"><button type="submit">Import (append)</button></div>'
    )
    parts.append("</form>")
    parts.append("</section>")
    return "".join(parts)


def _history_section(history: list[HistoryEntry] | None, clearable: bool) -> str:
    """The Search history card: recent queries and a clear-all button. Owner-only (loopback)."""
    if history is None:
        return ""
    parts = ['<section class="card"><h2>Search history</h2>']
    if history:
        parts.append('<ul class="histlist">')
        for entry in history:
            parts.append(f"<li>{escape(entry.query)}</li>")
        parts.append("</ul>")
        if clearable:
            parts.append(
                '<form class="histclear" action="/settings/history/clear" method="post">'
                '<button type="submit">Clear search history</button></form>'
            )
    else:
        parts.append(
            '<p class="hint">No search history (history is off, or nothing recorded yet).</p>'
        )
    parts.append("</section>")
    return "".join(parts)


def render_settings_page(
    prefs: UserPreferences,
    rules: RankingRules,
    saved: bool = False,
    history: list[HistoryEntry] | None = None,
    history_clearable: bool = False,
) -> str:
    """The browser Settings page: live preference toggles plus domain-rule and scope management.

    Owner-only (the server serves it to a loopback client and 404s otherwise). `saved` shows a brief
    confirmation after a successful POST. Mirrors the relevant parts of the desktop Settings dialog:
    the preference toggles map to `UserPreferences` fields; `rules` drives the domain-rule list, the
    scope (lens) editor, and the goggles list (all persisted to the encrypted ranking store); and
    `history`, when provided, shows recent queries with a clear-all button (`history_clearable`).
    Passing `history=None` omits the history card entirely.
    """
    head = _page_head("Settings · SearchMob")
    parts: list[str] = []
    parts.append('<body data-page="settings">')
    parts.append('<div class="topbar">')
    parts.append('<a href="/" class="logo">SearchMob</a>')
    parts.append('<span class="spacer"></span>')
    parts.append(_theme_toggle_button())
    parts.append("</div>")
    parts.append('<div class="settings">')
    parts.append("<h1>Settings</h1>")
    if saved:
        parts.append('<p class="saved" role="status">Saved.</p>')
    parts.append('<form action="/settings/prefs" method="post">')

    parts.append('<section class="card">')
    parts.append("<h2>Search &amp; ranking</h2>")
    parts.append('<div class="field"><label>Default sort</label>')
    parts.append(_select("sort_mode", _SORT_OPTIONS, prefs.sort_mode))
    parts.append("</div>")
    parts.append('<div class="field"><label>AI-slop / low-quality filter</label>')
    parts.append(_select("ai_slop_mode", _SLOP_OPTIONS, prefs.ai_slop_mode))
    parts.append(
        '<p class="hint">Applied on-device after your own domain rules, which always win.</p>'
    )
    parts.append("</div>")
    parts.append("</section>")

    parts.append('<section class="card">')
    parts.append("<h2>Suggestions</h2>")
    parts.append(
        _checkbox("summary_enabled", "Show the Wikipedia summary card", prefs.summary_enabled)
    )
    parts.append(
        _checkbox(
            "upstream_suggestions_enabled",
            "Use upstream autocomplete suggestions",
            prefs.upstream_suggestions_enabled,
        )
    )
    parts.append(
        '<p class="hint">Upstream autocomplete sends what you type to a suggestions service; '
        "your on-device history suggestions are always private.</p>"
    )
    parts.append("</section>")

    parts.append('<div class="actions"><button type="submit">Save</button></div>')
    parts.append("</form>")

    # Domain rules, scopes, goggles, and history are their own forms (each posts independently), so
    # they live outside the preferences form above.
    parts.append(_domain_rules_section(rules))
    parts.append(_lenses_section(rules))
    parts.append(_goggles_section(rules))
    parts.append(_history_section(history, history_clearable))

    parts.append("</div>")
    parts.append(f"<script>{_THEME_TOGGLE_JS}</script>")
    parts.append(f"<script>{_GOGGLE_FILE_JS}</script>")
    parts.append("</body>")
    return "<!DOCTYPE html><html lang='en'>" + head + "".join(parts) + "</html>"

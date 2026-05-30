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

from searchmob_desktop.engines import SearchResult
from searchmob_desktop.engines.rank import RankingRules, RankRule, host_of_url
from searchmob_desktop.engines.wiki_summary import SummaryBox

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
    ".verticalbar .chip.active{background:var(--accent);border-color:var(--accent);color:#fff;"
    "font-weight:600}"
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


def render_home_page() -> str:
    """The home page: a centered search box plus the OpenSearch link."""
    head = _page_head("SearchMob")
    body = (
        '<body data-page="home">'
        '<div class="topbar">'
        '<span class="logo">SearchMob</span>'
        f"{_theme_toggle_button()}"
        "</div>"
        '<div class="home">'
        '<div class="brand">SearchMob</div>'
        '<p class="tagline">Private, on-device metasearch.</p>'
        '<form action="/search" method="get" class="searchbox">'
        '<input type="text" name="q" placeholder="Search the web" '
        'autocomplete="off" autofocus="autofocus">'
        '<input type="submit" value="Search">'
        "</form>"
        "</div>"
        f"<script>{_THEME_TOGGLE_JS}</script>"
        "</body>"
    )
    return f"<!DOCTYPE html><html>{head}{body}</html>"


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
        active = " active" if value == vertical else ""
        href = f"/search?q={safe_q}&vertical={value}"
        chips.append(f'<a class="chip{active}" href="{escape(href, quote=True)}">{label}</a>')
    return '<nav class="verticalbar">' + "".join(chips) + "</nav>"


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
        "<label>Sort:</label>"
        '<select name="sort" onchange="this.form.submit()">' + "".join(options) + "</select>"
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
        "<label>Scope:</label>"
        '<select name="lens" onchange="this.form.submit()">' + "".join(options) + "</select>"
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
    parts.append('<div class="topbar">')
    parts.append('<a href="/" class="logo">SearchMob</a>')
    parts.append('<form action="/search" method="get" class="searchbox">')
    parts.append(
        '<input type="text" name="q" placeholder="Search the web" '
        f'value="{escape(query, quote=True)}" autocomplete="off" spellcheck="false">'
    )
    parts.append('<input type="submit" value="Search">')
    parts.append("</form>")
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
        for result in results_list:
            parts.append('<div class="result">')
            parts.append(f'<div class="url">{escape(_display_url(result.url))}</div>')
            if is_safe_http_url(result.url):
                # rel=noreferrer backs up the Referrer-Policy header so the query (in the loopback
                # URL) never leaks to the destination; noopener severs window.opener.
                parts.append(
                    f'<a href="{escape(result.url, quote=True)}" class="title" '
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
    return "<!DOCTYPE html><html>" + head + "".join(parts) + "</html>"

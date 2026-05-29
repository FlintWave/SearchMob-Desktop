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


def render_results_page(
    query: str,
    results: Iterable[SearchResult],
    is_safe_http_url: Callable[[str], bool],
    correction: str | None = None,
) -> str:
    """The results page. Empty/blank query -> a placeholder; otherwise -> the merged results.

    `query` must already be the length-clamped value the JSON endpoint also echoes; this renderer
    only escapes it for HTML safety. `is_safe_http_url` is the scheme-allowlist predicate so a
    `javascript:` or `data:` URL is rendered as plain text instead of an anchor.

    `correction`, when set, is a "did you mean" suggestion from the on-device corrector; it renders
    a link that re-runs the search with the corrected query.
    """
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

    if not blank and correction:
        href = "/search?q=" + quote_plus(correction)
        parts.append(
            '<p class="didyoumean">Did you mean: '
            f'<a href="{escape(href, quote=True)}">{escape(correction)}</a></p>'
        )

    if blank:
        parts.append('<p class="empty">Enter a query to search.</p>')
    elif not results_list:
        parts.append(f'<p class="empty">No results for “{safe_query}”.</p>')
    else:
        parts.append(f'<p class="meta">Results for “{safe_query}”</p>')
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
            parts.append("</div>")

    parts.append("</div>")
    parts.append(f"<script>{_THEME_TOGGLE_JS}</script>")
    parts.append("</body>")
    return "<!DOCTYPE html><html>" + head + "".join(parts) + "</html>"

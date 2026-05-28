"""Top-level CLI. Typer app with subcommands; the GUI launches via `searchmob-desktop gui`.

The CLI exists in its own right (headless servers, scripting) and is also the launcher the GUI shim
calls into, so both surfaces share the same library code.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import typer
from rich.console import Console
from rich.table import Table

from searchmob_desktop.engines import (
    EngineContext,
    EngineFn,
    SearchResult,
    aggregate,
    fetch_brave_api,
    fetch_duckduckgo,
    fetch_marginalia,
    fetch_mojeek,
    fetch_mojeek_api,
    fetch_mwmbl,
    fetch_wikipedia,
)
from searchmob_desktop.server import serve as _serve_local_server
from searchmob_desktop.version import __version__

app = typer.Typer(
    name="searchmob-desktop",
    help="SearchMob for Windows, macOS, and Linux. Private, on-device metasearch.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

# Env vars the CLI reads to enable the two BYO-key engines. Absent var means the engine is opt-in
# off and is not appended to the engine list, so no HTTP request goes out to that upstream at all.
_BRAVE_KEY_ENV = "SEARCHMOB_BRAVE_API_KEY"
_MOJEEK_KEY_ENV = "SEARCHMOB_MOJEEK_API_KEY"


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"SearchMob Desktop {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Print the version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Root callback so --version works at the top level."""


def _build_engines() -> list[EngineFn]:
    """Assemble the engine list: free engines always, BYO-key engines only when a key is set.

    When `SEARCHMOB_MOJEEK_API_KEY` is present we still keep the free Mojeek HTML adapter in the
    list. Dedup-by-URL in the aggregator already merges identical hits across the two, and the API
    surface returns more results when its key is good, so running both is a no-op when the key is
    valid and a useful fallback when the key has expired.
    """
    engines: list[EngineFn] = [
        fetch_duckduckgo,
        fetch_wikipedia,
        fetch_mojeek,
        fetch_marginalia,
        fetch_mwmbl,
    ]
    brave_key = os.environ.get(_BRAVE_KEY_ENV)
    if brave_key:

        async def _brave(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
            return await fetch_brave_api(client, ctx, api_key=brave_key)

        engines.append(_brave)
    mojeek_key = os.environ.get(_MOJEEK_KEY_ENV)
    if mojeek_key:

        async def _mojeek_api(client: httpx.AsyncClient, ctx: EngineContext) -> list[SearchResult]:
            return await fetch_mojeek_api(client, ctx, api_key=mojeek_key)

        engines.append(_mojeek_api)
    return engines


@app.command()
def search(
    query: str = typer.Argument(..., help="What to search for."),
    max_results: int = typer.Option(10, "--max-results", "-n", help="Max merged results to show."),
    timeout: float = typer.Option(5.0, "--timeout", help="Per-engine HTTP timeout, in seconds."),
) -> None:
    """Run a one-shot metasearch across the configured engines and print the merged results.

    Free engines (no setup): DuckDuckGo, Wikipedia, Mojeek, Marginalia, Mwmbl. Bring-your-own-key
    engines are enabled by setting `SEARCHMOB_BRAVE_API_KEY` and / or `SEARCHMOB_MOJEEK_API_KEY` in
    the environment; with no key set the corresponding engine is silently skipped (zero HTTP).
    """
    ctx = EngineContext(query=query, max_results=max_results, timeout_seconds=timeout)
    results = asyncio.run(aggregate(ctx, _build_engines()))

    if not results:
        console.print("[yellow]No results.[/]")
        raise typer.Exit(code=1)

    table = Table(title=f"Results for {query!r}", show_lines=False)
    table.add_column("Rank", justify="right", style="cyan", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("URL", style="blue")
    table.add_column("Engine", style="green")
    for rank, item in enumerate(results, start=1):
        table.add_row(str(rank), item.title, item.url, item.engine)
    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host. 127.0.0.1 is loopback-only."),
    port: int = typer.Option(8787, help="Bind port."),
    timeout: float = typer.Option(5.0, "--timeout", help="Per-engine HTTP timeout, in seconds."),
    max_results: int = typer.Option(
        10, "--max-results", "-n", help="Max merged results returned per query."
    ),
) -> None:
    """Start the local HTTP server so a browser can use SearchMob as its search engine.

    Routes mirror the Android Ktor server: `/`, `/search`, `/api/search`, `/healthz`,
    `/opensearch.xml`, and `/suggest`. Loopback-only by default; pass `--host 0.0.0.0` to expose
    on the LAN once Phase 7 lands. Engine selection (and BYO key handling) reuses `_build_engines`
    so the served metasearch matches `searchmob-desktop search` exactly.
    """
    console.print(f"[cyan]SearchMob Desktop[/] serving on http://{host}:{port}/")
    _serve_local_server(
        _build_engines(),
        host=host,
        port=port,
        max_results=max_results,
        timeout_seconds=timeout,
    )


@app.command()
def gui() -> None:
    """Launch the desktop GUI (PySide6). Placeholder until the GUI module is wired up."""
    console.print("[yellow]gui not yet implemented[/]")
    raise typer.Exit(code=2)


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()

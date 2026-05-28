"""Top-level CLI. Typer app with subcommands; the GUI launches via `searchmob-desktop gui`.

The CLI exists in its own right (headless servers, scripting) and is also the launcher the GUI shim
calls into, so both surfaces share the same library code.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from searchmob_desktop.engines import (
    EngineContext,
    aggregate,
    fetch_duckduckgo,
    fetch_wikipedia,
)
from searchmob_desktop.version import __version__

app = typer.Typer(
    name="searchmob-desktop",
    help="SearchMob for Windows, macOS, and Linux. Private, on-device metasearch.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


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


@app.command()
def search(
    query: str = typer.Argument(..., help="What to search for."),
    max_results: int = typer.Option(10, "--max-results", "-n", help="Max merged results to show."),
    timeout: float = typer.Option(5.0, "--timeout", help="Per-engine HTTP timeout, in seconds."),
) -> None:
    """Run a one-shot metasearch across DuckDuckGo and Wikipedia and print the merged results."""
    ctx = EngineContext(query=query, max_results=max_results, timeout_seconds=timeout)
    results = asyncio.run(aggregate(ctx, [fetch_duckduckgo, fetch_wikipedia]))

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
) -> None:
    """Start the local HTTP server so a browser can use SearchMob as its search engine.

    Placeholder until the Starlette/Uvicorn server module is wired up.
    """
    console.print(
        f"[yellow]serve not yet implemented; would bind[/] http://{host}:{port}/",
    )
    raise typer.Exit(code=2)


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

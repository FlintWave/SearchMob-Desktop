"""Top-level CLI. Typer app with subcommands; the GUI launches via `searchmob-desktop gui`.

The CLI exists in its own right (headless servers, scripting) and is also the launcher the GUI shim
calls into, so both surfaces share the same library code.
"""

from __future__ import annotations

import asyncio
import getpass
import os

import httpx
import typer
from rich.console import Console
from rich.table import Table

from searchmob_desktop.data import (
    ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING,
    BootstrapMetadataStore,
    StorageBootstrap,
    WrapMode,
)
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
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


vault_app = typer.Typer(
    name="vault",
    help="Manage the encrypted-storage vault (OS keyring or zero-knowledge passphrase).",
    no_args_is_help=True,
)
app.add_typer(vault_app, name="vault")


def _build_storage() -> StorageBootstrap:
    """Wire a `StorageBootstrap` against the OS keyring + the default metadata file location."""
    metadata_store = BootstrapMetadataStore()
    # The keyring fallback file sits next to the metadata file under the user data dir, so a user
    # who blows away the SearchMob data dir resets the whole vault as one atomic step.
    fallback_path = metadata_store.path.parent / "keyring-fallback.kek"
    kek_store = KeyringKekStore(fallback_file_path=fallback_path)
    keyring_wrapper = KeyringDekWrapper(kek_store)
    return StorageBootstrap(
        metadata_store=metadata_store,
        keyring_wrapper=keyring_wrapper,
        keyring_clearer=kek_store.clear,
    )


@vault_app.command("status")
def vault_status() -> None:
    """Print the current vault mode, whether it is unlocked, and where metadata lives."""
    storage = _build_storage()
    mode = storage.mode
    if mode is None:
        console.print("[yellow]vault: uninitialized[/] (no metadata file yet)")
    else:
        console.print(f"vault mode: [cyan]{mode.value}[/]")
    # `unlock_keyring` is a no-op + safe to call before anything else; surface the result so
    # `status` is informative for OS-mode vaults right out of the box.
    if mode == WrapMode.OS:
        storage.unlock_keyring()
    state = "unlocked" if storage.is_unlocked else "locked"
    console.print(
        f"state: [green]{state}[/]" if storage.is_unlocked else f"state: [yellow]{state}[/]"
    )
    console.print(f"metadata file: {storage.metadata_store.path}")


@vault_app.command("unlock")
def vault_unlock() -> None:
    """Unlock the vault. OS mode is silent; passphrase mode prompts."""
    storage = _build_storage()
    mode = storage.mode
    if mode is None:
        # First run: bootstrap implicitly so the user can start using the app right away.
        storage.first_run()
        console.print("[green]vault initialized in OS mode and unlocked.[/]")
        return
    if mode == WrapMode.OS:
        ok = storage.unlock_keyring()
        if ok:
            console.print("[green]vault unlocked (OS mode).[/]")
        else:
            console.print("[red]vault unlock failed: keyring entry missing or unreadable.[/]")
            raise typer.Exit(code=1)
        return
    # Passphrase mode.
    passphrase = bytearray(getpass.getpass("vault passphrase: ").encode("utf-8"))
    try:
        ok = storage.unlock_with_passphrase(passphrase)
    finally:
        # Zero the local buffer so the passphrase does not linger in memory longer than needed.
        for i in range(len(passphrase)):
            passphrase[i] = 0
    # Generic message either way; do not branch text on success / failure beyond pass/fail to
    # avoid leaking timing or error-class information.
    if ok:
        console.print("[green]vault unlocked.[/]")
    else:
        console.print("[red]wrong passphrase.[/]")
        raise typer.Exit(code=1)


@vault_app.command("set-passphrase")
def vault_set_passphrase() -> None:
    """Switch to zero-knowledge mode. Prints the unrecoverable-data warning first."""
    storage = _build_storage()
    if storage.mode is None:
        # Bootstrap first so there is a DEK to re-wrap.
        storage.first_run()
    elif storage.mode == WrapMode.OS and not storage.is_unlocked:
        storage.unlock_keyring()
    if not storage.is_unlocked:
        console.print("[red]vault must be unlocked first. Run `vault unlock`.[/]")
        raise typer.Exit(code=1)
    console.print(f"[yellow]{ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING}[/]")
    confirm = typer.prompt("Type 'I UNDERSTAND' to continue").strip()
    if confirm != "I UNDERSTAND":
        console.print("aborted.")
        raise typer.Exit(code=1)
    p1 = bytearray(getpass.getpass("new passphrase: ").encode("utf-8"))
    p2 = bytearray(getpass.getpass("confirm passphrase: ").encode("utf-8"))
    try:
        if bytes(p1) != bytes(p2):
            console.print("[red]passphrases do not match.[/]")
            raise typer.Exit(code=1)
        storage.enable_zero_knowledge(p1, warning_confirmed=True)
    finally:
        for buf in (p1, p2):
            for i in range(len(buf)):
                buf[i] = 0
    console.print("[green]zero-knowledge mode enabled.[/]")


@vault_app.command("clear-passphrase")
def vault_clear_passphrase() -> None:
    """Switch back to OS-keyring mode. Requires the vault to be unlocked first."""
    storage = _build_storage()
    if storage.mode != WrapMode.PASSPHRASE:
        console.print("vault is not in passphrase mode; nothing to clear.")
        raise typer.Exit(code=1)
    if not storage.is_unlocked:
        console.print("[red]vault must be unlocked first. Run `vault unlock`.[/]")
        raise typer.Exit(code=1)
    storage.disable_zero_knowledge()
    console.print("[green]zero-knowledge mode disabled. Vault is back to OS-keyring mode.[/]")


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

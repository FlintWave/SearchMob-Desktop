"""Top-level CLI. Typer app with subcommands; the GUI launches via `searchmob-desktop gui`.

The CLI exists in its own right (headless servers, scripting) and is also the launcher the GUI shim
calls into, so both surfaces share the same library code.
"""

from __future__ import annotations

import asyncio
import getpass
import threading
import time

import typer
from rich.console import Console
from rich.table import Table

from searchmob_desktop.data import (
    ZERO_KNOWLEDGE_UNRECOVERABLE_WARNING,
    BootstrapMetadataStore,
    StorageBootstrap,
    WrapMode,
)
from searchmob_desktop.data.api_keys import read_vault_api_keys, resolve_api_key
from searchmob_desktop.data.crypto.keyring_kek import KeyringKekStore
from searchmob_desktop.data.crypto.wrap import KeyringDekWrapper
from searchmob_desktop.data.history_factory import build_history_store
from searchmob_desktop.data.ranking_store import load_ranking_rules
from searchmob_desktop.engines import (
    EngineContext,
    EngineFn,
    aggregate,
    bind_api_key,
    fetch_brave_api,
    fetch_duckduckgo,
    fetch_kagi_api,
    fetch_marginalia,
    fetch_mojeek,
    fetch_mojeek_api,
    fetch_mwmbl,
    fetch_wikipedia,
)
from searchmob_desktop.engines.correct import start_background_corrector
from searchmob_desktop.engines.proxy import make_privacy_client
from searchmob_desktop.prefs import JsonPreferencesStore
from searchmob_desktop.server import is_loopback_host
from searchmob_desktop.server import serve as _serve_local_server
from searchmob_desktop.suggest import (
    CompositeSuggestionsProvider,
    HistorySuggestionsProvider,
    UpstreamSuggestionsProvider,
)
from searchmob_desktop.update import (
    RELEASES_PAGE_URL,
    UpdateInfo,
    VersionTag,
    check_if_due,
    fetch_latest,
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


def _build_engines() -> list[EngineFn]:
    """Assemble the engine list: free engines always, BYO-key engines only when a key is resolved.

    Each BYO key is resolved from the encrypted vault first (so a key saved in the GUI works on the
    CLI too) and then from the matching environment variable. With no key the engine is silently
    skipped, so no HTTP request goes out to that upstream at all.

    When the Mojeek API key is present we still keep the free Mojeek HTML adapter in the list.
    Dedup-by-URL in the aggregator already merges identical hits across the two, and the API surface
    returns more results when its key is good, so running both is a no-op when the key is valid and
    a useful fallback when the key has expired.
    """
    engines: list[EngineFn] = [
        fetch_duckduckgo,
        fetch_wikipedia,
        fetch_mojeek,
        fetch_marginalia,
        fetch_mwmbl,
    ]
    vault_keys = read_vault_api_keys()
    keyed = (
        ("brave", fetch_brave_api),
        ("mojeek-api", fetch_mojeek_api),
        ("kagi-api", fetch_kagi_api),
    )
    for engine_id, fetch in keyed:
        key = resolve_api_key(engine_id, vault_keys)
        if key:
            engines.append(bind_api_key(fetch, key))
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

    prefs_store = JsonPreferencesStore()
    prefs = prefs_store.load()
    # Persistent encrypted history when enabled + vault available, else in-memory (per-session).
    history_store = build_history_store(prefs)

    # Live read on every suggest call so a future settings UI toggle takes effect without
    # restarting the server. Today the toggle flips by editing prefs.json + restarting,
    # but the contract is forward-compatible.
    def _upstream_enabled() -> bool:
        try:
            return prefs_store.load().upstream_suggestions_enabled
        except OSError:
            return False

    composite = CompositeSuggestionsProvider(
        history=HistorySuggestionsProvider(history_store),
        upstream=UpstreamSuggestionsProvider(lambda: make_privacy_client(2.0)),
        upstream_enabled=_upstream_enabled,
        # Privacy guard: when bound to a network-reachable address, do not serve the owner's
        # local history as autocomplete to other devices on the network.
        local_enabled=lambda: is_loopback_host(host),
    )

    _run_update_check_in_background(prefs_store)

    # On-device "did you mean" for the browser results page. The dictionary loads off-thread, so
    # an early search before it is ready simply shows no suggestion. History terms feed the
    # vocabulary so corrections improve for queries the user actually runs.
    corrector = start_background_corrector(
        history_terms=lambda: [e.query for e in history_store.recent(500)]
    )

    # In network mode (non-loopback bind), gate the query routes with the persisted access token so
    # only clients that know it can run searches. Loopback binds never enforce, so pass None there.
    access_token = None if is_loopback_host(host) else (prefs.network_access_token or None)

    _serve_local_server(
        _build_engines(),
        host=host,
        port=port,
        suggestions_provider=composite,
        corrector=corrector,
        ranking_rules=load_ranking_rules(),
        max_results=max_results,
        timeout_seconds=timeout,
        access_token=access_token,
    )


def _current_version_code() -> int:
    parsed = VersionTag.parse(__version__)
    return parsed.to_version_code() if parsed else 0


def _run_update_check_in_background(prefs_store: JsonPreferencesStore) -> None:
    """Fire-and-forget the throttled GitHub update check on a thread.

    Never blocks server startup, never crashes the CLI: a bare `except Exception` swallows
    anything bubbling out (network, serialization, prefs IO). Prints an update banner via
    `console` if a newer release is found; otherwise stays silent.
    """

    def _do() -> None:
        try:
            prefs = prefs_store.load()
            now_ms = int(time.time() * 1000)
            info, stamped = asyncio.run(
                check_if_due(
                    prefs,
                    _current_version_code(),
                    now_ms=now_ms,
                    client_factory=lambda: make_privacy_client(4.0),
                )
            )
            if stamped != prefs.last_update_check_ms:
                prefs_store.save(prefs.with_update_check_stamped(stamped))
            if info is not None:
                _print_update_available(info)
        except Exception:
            return

    threading.Thread(target=_do, daemon=True).start()


def _print_update_available(info: UpdateInfo) -> None:
    v = info.latest_version
    console.print(
        f"[yellow]Update available:[/] [bold]{v.year:02d}.{v.month:02d}.{v.build:02d}[/]"
        f" -> {info.release_url}"
    )


update_app = typer.Typer(
    name="update",
    help="Check GitHub for a newer SearchMob Desktop release.",
    no_args_is_help=True,
)
app.add_typer(update_app, name="update")


@update_app.command("check")
def update_check() -> None:
    """Run the GitHub Releases update check now, bypassing the daily throttle.

    Prints whether a newer version is available and the releases URL. Returns exit code 0 either
    way; exit code 2 only on transport errors (so scripts can distinguish "no update" from "could
    not reach GitHub").
    """

    async def _probe() -> UpdateInfo | None:
        async with make_privacy_client(4.0) as client:
            return await fetch_latest(client)

    info = asyncio.run(_probe())
    current = _current_version_code()
    if info is None:
        console.print(
            f"[red]Could not reach GitHub.[/] Latest known check failed; you are running "
            f"{__version__}. Releases page: {RELEASES_PAGE_URL}"
        )
        raise typer.Exit(code=2)
    if info.is_newer_than(current):
        _print_update_available(info)
    else:
        console.print(
            f"[green]You're on the latest version[/] ({__version__}). "
            f"Latest published: {info.latest_version.year:02d}."
            f"{info.latest_version.month:02d}.{info.latest_version.build:02d}"
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
    """Launch the desktop GUI (PySide6).

    Imports of `PySide6` are deferred to inside `run_gui()` so the headless CLI never pays the
    Qt cost on startup; this subcommand exits cleanly if the `gui` extra was not installed.
    """
    try:
        from searchmob_desktop.gui import run_gui
    except ImportError as exc:
        console.print(
            f"[red]GUI unavailable:[/] {exc}. Install with: pip install searchmob-desktop[gui]"
        )
        raise typer.Exit(code=2) from exc
    raise typer.Exit(code=run_gui())


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()

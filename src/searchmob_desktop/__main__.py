"""Package entry point for the packaged desktop app.

The native installers (Briefcase) launch the app as ``python -m searchmob_desktop`` with no
arguments, so this must open the GUI window rather than the CLI. The Typer CLI is exposed
separately as the ``searchmob-desktop`` console script (see ``[project.scripts]``) for headless
and scripted use, and remains reachable via its ``gui`` / ``search`` / ``serve`` subcommands.

If any arguments are passed, or the GUI stack (PySide6) is not installed, we defer to the CLI so
``python -m searchmob_desktop search ...`` still works on a headless install.
"""

from __future__ import annotations

import sys


def main() -> None:
    # No arguments => the desktop-launch case: open the GUI window.
    if len(sys.argv) <= 1:
        try:
            from searchmob_desktop.gui.app import run_gui
        except ImportError:
            # GUI extra not installed (headless install); fall back to the CLI.
            from searchmob_desktop.cli import main as cli_main

            cli_main()
            return
        raise SystemExit(run_gui())

    # Arguments present => behave like the CLI (`python -m searchmob_desktop search ...`).
    from searchmob_desktop.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()

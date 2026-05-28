"""Smoke tests so CI has something to run from day one. Real tests land with each feature."""

from typer.testing import CliRunner

from searchmob_desktop.cli import app
from searchmob_desktop.version import __version__


def test_version_is_a_date_string() -> None:
    """Version follows YY.MM.VV; the build derives versionCode from it on the Android side."""
    parts = __version__.split(".")
    assert len(parts) == 3, __version__
    for part in parts:
        assert part.isdigit() and len(part) == 2, __version__


def test_cli_version_flag_prints_and_exits() -> None:
    """`searchmob-desktop --version` must print the version and exit cleanly."""
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert __version__ in result.output


def test_cli_help_lists_subcommands() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for name in ("search", "serve", "gui"):
        assert name in result.output

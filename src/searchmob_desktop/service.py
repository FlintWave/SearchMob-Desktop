"""Run SearchMob's local server as a background service.

On Linux this manages a **systemd user unit** (`~/.config/systemd/user/searchmob-desktop.service`)
that runs the headless HTTP server (`serve`), so a browser can use SearchMob even when the GUI is
not open. The GUI still opens on a normal launch; this is an opt-in extra set up from Settings.

Only Linux/systemd is supported today. On other platforms `is_supported()` is False and the
Settings UI shows an explanatory note instead of the install controls. Everything here is
fail-soft: a missing `systemctl`, an unwritable unit dir, or a non-zero `systemctl` exit returns a
`(False, message)` rather than raising, so the UI can surface the problem without crashing.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_NAME = "searchmob-desktop.service"
DEFAULT_PORT = 8787


@dataclass(frozen=True)
class ServiceStatus:
    """A snapshot of the background service's state, for the Settings UI to render."""

    supported: bool
    installed: bool
    enabled: bool
    active: bool

    def summary(self) -> str:
        if not self.supported:
            return "Background service is only available on Linux (systemd)."
        if not self.installed:
            return "Not installed."
        bits = []
        bits.append("running" if self.active else "stopped")
        bits.append("starts at login" if self.enabled else "manual start")
        return "Installed (" + ", ".join(bits) + ")."


def _config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base)


def unit_path() -> Path:
    """Where the systemd user unit lives."""
    return _config_home() / "systemd" / "user" / SERVICE_NAME


def is_supported() -> bool:
    """True only on Linux with a reachable `systemctl` (the user-unit manager)."""
    return sys.platform.startswith("linux") and shutil.which("systemctl") is not None


def server_command(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> list[str]:
    """The command the unit runs to start the headless server.

    Prefers the installed `searchmob-desktop` console script (pipx / source installs); otherwise
    invokes the running interpreter with `-m searchmob_desktop`, which the bundled app supports.
    """
    console = shutil.which("searchmob-desktop")
    base = [console] if console else [sys.executable, "-m", "searchmob_desktop"]
    return [*base, "serve", "--host", host, "--port", str(port)]


def unit_text(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> str:
    """Render the systemd unit file contents for the given bind host/port."""
    exec_start = " ".join(shlex.quote(part) for part in server_command(host, port))
    return (
        "[Unit]\n"
        "Description=SearchMob Desktop local search server\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def status() -> ServiceStatus:
    """Inspect the current service state (unsupported platforms report all-False)."""
    if not is_supported():
        return ServiceStatus(supported=False, installed=False, enabled=False, active=False)
    installed = unit_path().is_file()
    enabled = _systemctl("is-enabled", SERVICE_NAME).stdout.strip() == "enabled"
    active = _systemctl("is-active", SERVICE_NAME).stdout.strip() == "active"
    return ServiceStatus(supported=True, installed=installed, enabled=enabled, active=active)


def install_and_enable(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Write the unit, enable it at login, and start it now. Returns `(ok, message)`."""
    if not is_supported():
        return (False, "Background service is only available on Linux (systemd).")
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_text(host, port), encoding="utf-8")
    except OSError as exc:
        return (False, f"Could not write the service file: {exc}")
    _systemctl("daemon-reload")
    result = _systemctl("enable", "--now", SERVICE_NAME)
    if result.returncode != 0:
        return (False, result.stderr.strip() or "systemctl could not enable the service.")
    return (True, "Service installed; it will run in the background and start at login.")


def disable_and_remove() -> tuple[bool, str]:
    """Stop and disable the service, then remove the unit file. Returns `(ok, message)`."""
    if not is_supported():
        return (False, "Background service is only available on Linux (systemd).")
    _systemctl("disable", "--now", SERVICE_NAME)
    try:
        unit_path().unlink(missing_ok=True)
    except OSError as exc:
        return (False, f"Could not remove the service file: {exc}")
    _systemctl("daemon-reload")
    return (True, "Service stopped and removed.")

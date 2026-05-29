"""Run SearchMob's local server as a per-user background service, cross-platform.

A browser can then use SearchMob even when the app window is closed. The GUI still opens on a
normal launch; this is an opt-in extra set up from Settings. Three per-user backends, no admin
rights required:

* **Linux** - a systemd *user* unit (`~/.config/systemd/user/searchmob-desktop.service`).
* **macOS** - a launchd *LaunchAgent* under `~/Library/LaunchAgents/`.
* **Windows** - a *Scheduled Task* that runs at logon (`schtasks`).

The public API (`is_supported`, `status`, `install_and_enable`, `disable_and_remove`) dispatches on
the platform; an unsupported platform reports `supported=False` so the Settings UI shows a note
instead of the controls. Everything is fail-soft: a missing tool, an unwritable path, or a non-zero
exit returns `(False, message)` rather than raising.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

# Identifiers, one per backend; kept stable so an upgrade manages the same unit/agent/task.
SYSTEMD_UNIT = "searchmob-desktop.service"
LAUNCHD_LABEL = "com.flintwave.searchmob-desktop"
WINDOWS_TASK = "SearchMobDesktop"
DEFAULT_PORT = 8787


@dataclass(frozen=True)
class ServiceStatus:
    """A snapshot of the background service's state, for the Settings UI to render."""

    supported: bool
    installed: bool
    enabled: bool  # will start automatically (at login)
    active: bool  # running right now

    def summary(self) -> str:
        if not self.supported:
            return "Background service is not available on this platform yet."
        if not self.installed:
            return "Not installed."
        bits = ["running" if self.active else "stopped"]
        if self.enabled:
            bits.append("starts at login")
        return "Installed (" + ", ".join(bits) + ")."


def _backend() -> str:
    """Which service mechanism this platform uses: systemd / launchd / schtasks / unsupported."""
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        return "systemd"
    if sys.platform == "darwin" and shutil.which("launchctl"):
        return "launchd"
    if sys.platform == "win32" and shutil.which("schtasks"):
        return "schtasks"
    return "unsupported"


def is_supported() -> bool:
    """True when this platform has a usable per-user service mechanism."""
    return _backend() != "unsupported"


def mechanism_label() -> str | None:
    """A human phrase for this platform's service mechanism, or None when unsupported.

    Used by the setup wizard / Settings to describe what installing the background service does in
    platform-accurate terms.
    """
    return {
        "systemd": "a systemd user service",
        "launchd": "a launchd agent",
        "schtasks": "a Windows scheduled task that runs at sign-in",
    }.get(_backend())


def server_command(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> list[str]:
    """The command a unit/agent/task runs to start the headless server.

    Prefers the installed `searchmob-desktop` console script (pipx / source installs); otherwise
    invokes the running interpreter with `-m searchmob_desktop`, which the bundled app supports.
    """
    console = shutil.which("searchmob-desktop")
    base = [console] if console else [sys.executable, "-m", "searchmob_desktop"]
    return [*base, "serve", "--host", host, "--port", str(port)]


def status() -> ServiceStatus:
    """Inspect the current service state (unsupported platforms report all-False)."""
    backend = _backend()
    if backend == "systemd":
        return _systemd_status()
    if backend == "launchd":
        return _launchd_status()
    if backend == "schtasks":
        return _schtasks_status()
    return ServiceStatus(supported=False, installed=False, enabled=False, active=False)


def install_and_enable(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Install the service, set it to start at login, and start it now. Returns `(ok, message)`."""
    backend = _backend()
    if backend == "systemd":
        return _systemd_install(host, port)
    if backend == "launchd":
        return _launchd_install(host, port)
    if backend == "schtasks":
        return _schtasks_install(host, port)
    return (False, "Background service is not available on this platform yet.")


def disable_and_remove() -> tuple[bool, str]:
    """Stop the service, disable autostart, and remove it. Returns `(ok, message)`."""
    backend = _backend()
    if backend == "systemd":
        return _systemd_remove()
    if backend == "launchd":
        return _launchd_remove()
    if backend == "schtasks":
        return _schtasks_remove()
    return (False, "Background service is not available on this platform yet.")


# --- Linux: systemd user unit ----------------------------------------------------------------


def _config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base)


def unit_path() -> Path:
    """Where the systemd user unit lives (Linux)."""
    return _config_home() / "systemd" / "user" / SYSTEMD_UNIT


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
        ["systemctl", "--user", *args], capture_output=True, text=True, check=False
    )


def _systemd_status() -> ServiceStatus:
    installed = unit_path().is_file()
    enabled = _systemctl("is-enabled", SYSTEMD_UNIT).stdout.strip() == "enabled"
    active = _systemctl("is-active", SYSTEMD_UNIT).stdout.strip() == "active"
    return ServiceStatus(supported=True, installed=installed, enabled=enabled, active=active)


def _systemd_install(host: str, port: int) -> tuple[bool, str]:
    path = unit_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit_text(host, port), encoding="utf-8")
    except OSError as exc:
        return (False, f"Could not write the service file: {exc}")
    _systemctl("daemon-reload")
    result = _systemctl("enable", "--now", SYSTEMD_UNIT)
    if result.returncode != 0:
        return (False, result.stderr.strip() or "systemctl could not enable the service.")
    return (True, "Service installed; it will run in the background and start at login.")


def _systemd_remove() -> tuple[bool, str]:
    _systemctl("disable", "--now", SYSTEMD_UNIT)
    try:
        unit_path().unlink(missing_ok=True)
    except OSError as exc:
        return (False, f"Could not remove the service file: {exc}")
    _systemctl("daemon-reload")
    return (True, "Service stopped and removed.")


# --- macOS: launchd LaunchAgent --------------------------------------------------------------


def plist_path() -> Path:
    """Where the launchd LaunchAgent plist lives (macOS)."""
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def plist_text(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> str:
    """Render the LaunchAgent plist for the given bind host/port."""
    args = "".join(
        f"        <string>{_xml_escape(part)}</string>\n" for part in server_command(host, port)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        f"    <key>Label</key>\n    <string>{LAUNCHD_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        f"    <array>\n{args}    </array>\n"
        "    <key>RunAtLoad</key>\n    <true/>\n"
        "    <key>KeepAlive</key>\n    <true/>\n"
        "</dict>\n"
        "</plist>\n"
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _launchd_status() -> ServiceStatus:
    installed = plist_path().is_file()
    # `launchctl list <label>` exits 0 when the agent is loaded.
    loaded = _launchctl("list", LAUNCHD_LABEL).returncode == 0
    # RunAtLoad means a loaded agent autostarts; treat loaded as both enabled and active.
    return ServiceStatus(supported=True, installed=installed, enabled=loaded, active=loaded)


def _launchd_install(host: str, port: int) -> tuple[bool, str]:
    path = plist_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist_text(host, port), encoding="utf-8")
    except OSError as exc:
        return (False, f"Could not write the LaunchAgent: {exc}")
    # `load -w` registers the agent and marks it to load at login. Reload defensively first.
    _launchctl("unload", str(path))
    result = _launchctl("load", "-w", str(path))
    if result.returncode != 0:
        return (False, result.stderr.strip() or "launchctl could not load the service.")
    return (True, "Service installed; it will run in the background and start at login.")


def _launchd_remove() -> tuple[bool, str]:
    path = plist_path()
    _launchctl("unload", "-w", str(path))
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        return (False, f"Could not remove the LaunchAgent: {exc}")
    return (True, "Service stopped and removed.")


# --- Windows: Scheduled Task at logon --------------------------------------------------------


def task_run_command(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> str:
    """The single command string schtasks runs (`/tr`), with each argument quoted."""
    return subprocess.list2cmdline(server_command(host, port))


def _schtasks(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, check=False)


def _schtasks_status() -> ServiceStatus:
    query = _schtasks("/query", "/tn", WINDOWS_TASK, "/v", "/fo", "list")
    installed = query.returncode == 0
    active = installed and "running" in query.stdout.lower()
    # A logon-triggered task autostarts; equate enabled with installed.
    return ServiceStatus(supported=True, installed=installed, enabled=installed, active=active)


def _schtasks_install(host: str, port: int) -> tuple[bool, str]:
    create = _schtasks(
        "/create",
        "/tn",
        WINDOWS_TASK,
        "/tr",
        task_run_command(host, port),
        "/sc",
        "onlogon",
        "/f",
    )
    if create.returncode != 0:
        return (False, create.stderr.strip() or "schtasks could not create the task.")
    # Start it now too, so the user does not have to log out and back in.
    _schtasks("/run", "/tn", WINDOWS_TASK)
    return (True, "Service installed; it will run in the background and start at login.")


def _schtasks_remove() -> tuple[bool, str]:
    result = _schtasks("/delete", "/tn", WINDOWS_TASK, "/f")
    if result.returncode != 0:
        return (False, result.stderr.strip() or "schtasks could not delete the task.")
    return (True, "Service stopped and removed.")

"""Unit tests for the cross-platform background-service manager.

No real `systemctl` / `launchctl` / `schtasks` is invoked: the per-backend runner is monkeypatched
to record calls and return a canned result, the active backend is forced via `_backend`, and file
paths are redirected into a tmp dir. This keeps the policy verifiable on any host (the CI runner is
Linux, but the macOS/Windows backends are exercised here too).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from searchmob_desktop import service


def _ok(*_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=0, stdout="", stderr="")


# --- shared / pure -----------------------------------------------------------------------------


def test_server_command_runs_serve_with_host_and_port() -> None:
    cmd = service.server_command(host="0.0.0.0", port=8787)
    assert cmd[-5:] == ["serve", "--host", "0.0.0.0", "--port", "8787"]
    assert cmd[0]  # an executable (console script or interpreter)


def test_server_command_frozen_app_omits_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged binary must be invoked as `<exe> serve ...` with NO `-m`.

    Regression for the broken systemd unit: the frozen `/usr/bin/searchmob_desktop` routes its argv
    straight to the CLI, so `-m` produced "No such option: -m" and a restart loop. With no console
    script on PATH and a non-`python` executable, the command must not contain `-m`.
    """
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    monkeypatch.setattr(service.sys, "executable", "/usr/bin/searchmob_desktop")
    cmd = service.server_command(host="127.0.0.1", port=8787)
    assert cmd == ["/usr/bin/searchmob_desktop", "serve", "--host", "127.0.0.1", "--port", "8787"]
    assert "-m" not in cmd


def test_server_command_plain_interpreter_uses_dash_m(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real `python` interpreter must be invoked with `-m searchmob_desktop`."""
    monkeypatch.setattr(service.shutil, "which", lambda _name: None)
    monkeypatch.setattr(service.sys, "executable", "/usr/bin/python3.12")
    monkeypatch.delattr(service.sys, "frozen", raising=False)
    cmd = service.server_command(host="127.0.0.1", port=8787)
    assert cmd[:3] == ["/usr/bin/python3.12", "-m", "searchmob_desktop"]


def test_server_command_console_script_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An installed `searchmob-desktop` console script is invoked directly (no `-m`)."""
    monkeypatch.setattr(service.shutil, "which", lambda _name: "/usr/local/bin/searchmob-desktop")
    cmd = service.server_command()
    assert cmd[0] == "/usr/local/bin/searchmob-desktop"
    assert "-m" not in cmd


def test_status_unsupported_is_all_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_backend", lambda: "unsupported")
    state = service.status()
    assert state == service.ServiceStatus(False, False, False, False)
    assert "not available" in state.summary()


def test_install_and_remove_unsupported_are_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_backend", lambda: "unsupported")
    assert service.install_and_enable()[0] is False
    assert service.disable_and_remove()[0] is False


def test_status_summary_phrasing() -> None:
    assert "Not installed" in service.ServiceStatus(True, False, False, False).summary()
    running = service.ServiceStatus(True, True, True, True).summary()
    assert "running" in running and "login" in running


# --- Linux: systemd ----------------------------------------------------------------------------


def test_systemd_unit_text_is_valid_looking() -> None:
    text = service.unit_text(host="127.0.0.1", port=8787)
    assert "[Service]" in text
    assert "WantedBy=default.target" in text
    assert "serve --host 127.0.0.1 --port 8787" in text


def test_systemd_install_writes_unit_and_enables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "_backend", lambda: "systemd")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a) or _ok(*a))
    # Do not touch the real `loginctl`; just record that lingering was requested.
    linger: list[bool] = []
    monkeypatch.setattr(service, "_enable_linger", lambda: linger.append(True) or True)

    ok, msg = service.install_and_enable(host="127.0.0.1", port=8787)
    assert ok
    assert "ExecStart=" in service.unit_path().read_text(encoding="utf-8")
    assert ("daemon-reload",) in calls
    assert ("enable", "--now", service.SYSTEMD_UNIT) in calls
    # Lingering is what makes it start at boot, so the install attempts it and says so.
    assert linger == [True]
    assert "starts with your system" in msg


def test_systemd_install_reports_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "_backend", lambda: "systemd")

    def _fail(*args: str) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("enable",):
            return subprocess.CompletedProcess(list(args), 1, "", "boom")
        return _ok(*args)

    monkeypatch.setattr(service, "_systemctl", _fail)
    ok, msg = service.install_and_enable()
    assert not ok and "boom" in msg


def test_systemd_remove_disables_and_deletes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "_backend", lambda: "systemd")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a) or _ok(*a))
    service.unit_path().parent.mkdir(parents=True, exist_ok=True)
    service.unit_path().write_text("stub", encoding="utf-8")

    ok, _ = service.disable_and_remove()
    assert ok
    assert not service.unit_path().exists()
    assert ("disable", "--now", service.SYSTEMD_UNIT) in calls


# --- macOS: launchd ----------------------------------------------------------------------------


def test_launchd_plist_text_has_label_and_args() -> None:
    text = service.plist_text(host="127.0.0.1", port=8787)
    assert f"<string>{service.LAUNCHD_LABEL}</string>" in text
    assert "<key>ProgramArguments</key>" in text
    assert "<string>serve</string>" in text
    assert "<key>RunAtLoad</key>" in text


def test_launchd_install_writes_plist_and_loads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / f"{service.LAUNCHD_LABEL}.plist"
    monkeypatch.setattr(service, "_backend", lambda: "launchd")
    monkeypatch.setattr(service, "plist_path", lambda: plist)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_launchctl", lambda *a: calls.append(a) or _ok(*a))

    ok, _ = service.install_and_enable(host="0.0.0.0", port=8787)
    assert ok
    assert plist.is_file()
    assert any(a[:2] == ("load", "-w") for a in calls)


def test_launchd_remove_unloads_and_deletes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plist = tmp_path / f"{service.LAUNCHD_LABEL}.plist"
    plist.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(service, "_backend", lambda: "launchd")
    monkeypatch.setattr(service, "plist_path", lambda: plist)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_launchctl", lambda *a: calls.append(a) or _ok(*a))

    ok, _ = service.disable_and_remove()
    assert ok
    assert not plist.exists()
    assert any(a[0] == "unload" for a in calls)


# --- Windows: schtasks -------------------------------------------------------------------------


def test_windows_run_command_quotes_arguments() -> None:
    cmd = service.task_run_command(host="127.0.0.1", port=8787)
    assert "serve" in cmd and "--host" in cmd and "8787" in cmd


def test_schtasks_install_creates_logon_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_backend", lambda: "schtasks")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_schtasks", lambda *a: calls.append(a) or _ok(*a))

    ok, _ = service.install_and_enable()
    assert ok
    create = next(a for a in calls if a[0] == "/create")
    assert "/tn" in create and service.WINDOWS_TASK in create
    assert "onlogon" in create


def test_schtasks_remove_deletes_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_backend", lambda: "schtasks")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_schtasks", lambda *a: calls.append(a) or _ok(*a))

    ok, _ = service.disable_and_remove()
    assert ok
    assert any(a[0] == "/delete" for a in calls)


def test_schtasks_status_parses_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "_backend", lambda: "schtasks")

    def _query(*_a: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["schtasks"], 0, "Status: Running\n", "")

    monkeypatch.setattr(service, "_schtasks", _query)
    state = service.status()
    assert state.installed and state.active

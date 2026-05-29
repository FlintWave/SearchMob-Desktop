"""Unit tests for the background-service manager (`searchmob_desktop.service`).

`systemctl` is never actually invoked: `_systemctl` is monkeypatched to record calls and return a
canned result, and `XDG_CONFIG_HOME` is redirected to a tmp dir so the unit file is written into
the sandbox. This keeps the policy (what gets written, which systemctl verbs run, how status is
parsed, how unsupported platforms degrade) verifiable without touching the real user session.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from searchmob_desktop import service


def test_server_command_runs_serve_with_host_and_port() -> None:
    cmd = service.server_command(host="0.0.0.0", port=8787)
    assert cmd[-5:] == ["serve", "--host", "0.0.0.0", "--port", "8787"]
    # The leading entry is an executable that exists (the console script or the interpreter).
    assert cmd[0]


def test_unit_text_is_a_valid_looking_unit() -> None:
    text = service.unit_text(host="127.0.0.1", port=8787)
    assert "[Service]" in text
    assert "ExecStart=" in text
    assert "WantedBy=default.target" in text
    assert "serve --host 127.0.0.1 --port 8787" in text


def test_status_unsupported_is_all_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "is_supported", lambda: False)
    state = service.status()
    assert state == service.ServiceStatus(
        supported=False, installed=False, enabled=False, active=False
    )
    assert "Linux" in state.summary()


def _ok(*_args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["systemctl"], returncode=0, stdout="", stderr="")


def test_install_writes_unit_and_enables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "is_supported", lambda: True)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a) or _ok(*a))

    ok, _msg = service.install_and_enable(host="127.0.0.1", port=8787)
    assert ok
    unit = service.unit_path()
    assert unit.is_file()
    assert "ExecStart=" in unit.read_text(encoding="utf-8")
    # daemon-reload then enable --now were issued.
    assert ("daemon-reload",) in calls
    assert ("enable", "--now", service.SERVICE_NAME) in calls


def test_install_reports_systemctl_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "is_supported", lambda: True)

    def _fail(*args: str) -> subprocess.CompletedProcess[str]:
        if args[:1] == ("enable",):
            return subprocess.CompletedProcess(
                args=list(args), returncode=1, stdout="", stderr="boom"
            )
        return _ok(*args)

    monkeypatch.setattr(service, "_systemctl", _fail)
    ok, msg = service.install_and_enable()
    assert not ok
    assert "boom" in msg


def test_remove_disables_and_deletes_unit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "is_supported", lambda: True)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(service, "_systemctl", lambda *a: calls.append(a) or _ok(*a))

    service.unit_path().parent.mkdir(parents=True, exist_ok=True)
    service.unit_path().write_text("stub", encoding="utf-8")

    ok, _msg = service.disable_and_remove()
    assert ok
    assert not service.unit_path().exists()
    assert ("disable", "--now", service.SERVICE_NAME) in calls


def test_install_and_remove_unsupported_are_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "is_supported", lambda: False)
    assert service.install_and_enable()[0] is False
    assert service.disable_and_remove()[0] is False


def test_status_summary_phrasing() -> None:
    assert "Not installed" in service.ServiceStatus(True, False, False, False).summary()
    running = service.ServiceStatus(True, True, True, True).summary()
    assert "running" in running and "login" in running

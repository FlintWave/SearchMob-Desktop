"""`probe_local_server`: detect an already-running server so the GUI can reuse the service.

The probe is a plain loopback socket GET to `/healthz`. We exercise both outcomes with a tiny
one-shot socket "server": a 200 with an `ok` body (reuse), and a closed port (start our own).
"""

from __future__ import annotations

import socket
import threading

import pytest

pytest.importorskip("PySide6")

from searchmob_desktop.gui.server_controller import probe_local_server


def _one_shot_server(response: bytes) -> tuple[int, threading.Thread]:
    """Bind a loopback socket that answers exactly one connection with `response`, then closes."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def serve() -> None:
        listener.settimeout(2.0)
        try:
            conn, _ = listener.accept()
        except OSError:
            listener.close()
            return
        with conn:
            try:
                conn.recv(1024)
                conn.sendall(response)
            except OSError:
                pass
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, thread


def test_probe_true_when_healthz_answers_ok() -> None:
    port, thread = _one_shot_server(b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nok")
    try:
        assert probe_local_server("127.0.0.1", port) is True
    finally:
        thread.join(timeout=2.0)


def test_probe_false_on_closed_port() -> None:
    # Bind then immediately release a port so it is almost certainly closed when we probe it.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    closed_port = sock.getsockname()[1]
    sock.close()
    assert probe_local_server("127.0.0.1", closed_port, timeout=0.3) is False


def test_probe_false_on_non_200() -> None:
    port, thread = _one_shot_server(b"HTTP/1.0 404 Not Found\r\n\r\nnope")
    try:
        assert probe_local_server("127.0.0.1", port) is False
    finally:
        thread.join(timeout=2.0)


def test_probe_maps_wildcard_bind_to_loopback() -> None:
    # A 0.0.0.0 bind is probed on 127.0.0.1, where the service also listens.
    port, thread = _one_shot_server(b"HTTP/1.0 200 OK\r\n\r\nok")
    try:
        assert probe_local_server("0.0.0.0", port) is True
    finally:
        thread.join(timeout=2.0)

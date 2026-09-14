"""Synthetic listeners only; never probe an installed Agent's port."""
import socket
from http.server import BaseHTTPRequestHandler
import pytest
from client.agent.local_server import ThreadingHTTPServer


def test_agent_listener_cannot_be_shared_by_another_server():
    first = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
    try:
        with pytest.raises(OSError):
            second = ThreadingHTTPServer(first.server_address, BaseHTTPRequestHandler)
            second.server_close()
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            assert first.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 1
    finally:
        first.server_close()

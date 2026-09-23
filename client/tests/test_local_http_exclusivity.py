"""Use ephemeral synthetic sockets only; never touch an installed client's port."""
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer as LegacyHTTPServer

import pytest

from client.runtime.local_http import HTTPServer, ThreadingHTTPServer


@pytest.mark.parametrize("server_type", [HTTPServer, ThreadingHTTPServer])
def test_listener_is_exclusive(server_type):
    with server_type(("127.0.0.1", 0), BaseHTTPRequestHandler) as first:
        assert first.allow_reuse_address is False
        assert first.allow_reuse_port is False
        with pytest.raises(OSError):
            with server_type(first.server_address, BaseHTTPRequestHandler):
                pytest.fail("two servers shared one listener")
        # An older process which requests SO_REUSEADDR must also be rejected.
        with pytest.raises(OSError):
            with LegacyHTTPServer(first.server_address, BaseHTTPRequestHandler):
                pytest.fail("legacy server stole an exclusive listener")
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            assert first.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 1


@pytest.mark.parametrize("server_type", [HTTPServer, ThreadingHTTPServer])
def test_exclusive_server_rejects_an_existing_legacy_listener(server_type):
    with LegacyHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as existing:
        with pytest.raises(OSError):
            with server_type(existing.server_address, BaseHTTPRequestHandler):
                pytest.fail("new server shared a legacy listener")
        # A genuinely free alternative remains usable.
        with server_type(("127.0.0.1", 0), BaseHTTPRequestHandler) as alternative:
            assert alternative.server_address != existing.server_address


def test_desktop_and_agent_use_exclusive_implementations():
    from client.agent import local_server
    from client.ui import main
    assert local_server.ThreadingHTTPServer is ThreadingHTTPServer
    assert main.HTTPServer is HTTPServer

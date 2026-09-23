"""Exclusive loopback listeners: never share a desktop/Agent port on Windows."""

import socket
from http.server import HTTPServer as _HTTPServer, ThreadingHTTPServer as _ThreadingHTTPServer


class _ExclusiveBind:
    # HTTPServer enables SO_REUSEADDR by default; on Windows this can allow two
    # live listeners to bind the same address and route requests unpredictably.
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class HTTPServer(_ExclusiveBind, _HTTPServer):
    pass


class ThreadingHTTPServer(_ExclusiveBind, _ThreadingHTTPServer):
    pass

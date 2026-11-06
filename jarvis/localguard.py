"""Keep the HUD server for the local app, not for whatever web page is open.

Binding to 127.0.0.1 isn't enough on its own. Browsers don't apply the
same-origin policy to websockets, so any site you visit can open
ws://127.0.0.1:8765/ws and talk to Jarvis, including answering its own
confirmation prompt. DNS rebinding reaches the server under another hostname.
Two checks, on both HTTP and websocket requests:

- Host must be a loopback name (defeats DNS rebinding).
- If an Origin header is present on a websocket or a state-changing request,
  it must be a loopback origin on this server's port (or the Vite dev server's).
  Requests with no Origin (curl, the CLI, Electron loading its own page) pass:
  a browser always sends one on a websocket and on a cross-site POST/DELETE.
"""
import json
from urllib.parse import urlsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
DEV_PORTS = {5173}      # the Vite dev server proxies to us
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _split_host(value):
    """(hostname, port or None) from a Host header, or (None, None)."""
    try:
        parts = urlsplit("//" + value)
        return parts.hostname, parts.port
    except ValueError:
        return None, None


def host_ok(host_header):
    name, _ = _split_host(host_header or "")
    return name in LOOPBACK


def origin_ok(origin, host_header):
    """A loopback origin whose port is this server's (or the dev server's)."""
    if origin == "null":
        return False
    try:
        parts = urlsplit(origin)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK:
        return False
    _, host_port = _split_host(host_header or "")
    default = 443 if parts.scheme == "https" else 80
    return (port or default) in ({host_port or default} | DEV_PORTS)


class LocalOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host, origin = headers.get("host"), headers.get("origin")
        needs_origin = scope["type"] == "websocket" or scope.get("method", "GET") not in SAFE_METHODS
        if not host_ok(host) or (origin is not None and needs_origin and not origin_ok(origin, host)):
            return await self._refuse(scope, receive, send)
        return await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope, receive, send):
        if scope["type"] == "websocket":
            await receive()                      # the connect event
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": "Jarvis only answers requests from its own app."}).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

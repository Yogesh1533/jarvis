"""Offline test for the HUD server's Host/Origin guard.

A web page you have open can reach http://127.0.0.1:8765 and ws://127.0.0.1:8765/ws
(browsers don't apply same-origin rules to websockets), and DNS rebinding can
reach it under another hostname. The guard must refuse both.

Run:  .venv/bin/python tests/web_guard_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route, WebSocketRoute  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from jarvis.localguard import LocalOnly  # noqa: E402

PASS = []


def check(name, cond):
    assert cond, "FAILED: {}".format(name)
    PASS.append(name)
    print("  ok - {}".format(name))


async def ok(request):
    return PlainTextResponse("hi")


async def ws(sock):
    await sock.accept()
    await sock.send_text("hello")
    await sock.close()


app = Starlette(routes=[Route("/api/x", ok, methods=["GET", "POST", "DELETE"]), WebSocketRoute("/ws", ws)])
app.add_middleware(LocalOnly)
client = TestClient(app, base_url="http://127.0.0.1:8765")


def get(path="/api/x", method="GET", **headers):
    return client.request(method, path, headers=headers).status_code


def ws_ok(**headers):
    try:
        with client.websocket_connect("/ws", headers=headers) as s:
            return s.receive_text() == "hello"
    except WebSocketDisconnect:
        return False


print("== HTTP ==")
check("same-origin GET with loopback host is allowed", get(host="127.0.0.1:8765") == 200)
check("localhost host is allowed", get(host="localhost:8765") == 200)
check("IPv6 loopback host is allowed", get(host="[::1]:8765") == 200)
check("no Origin header (curl, Electron fetch of own page, CLI) is allowed", get(host="127.0.0.1:8765") == 200)
check("DNS rebinding: foreign Host is refused", get(host="evil.example.com:8765") == 403)
check("foreign Host that merely starts with 127.0.0.1 is refused", get(host="127.0.0.1.evil.com:8765") == 403)
check("foreign Host that merely contains localhost is refused", get(host="localhost.evil.com") == 403)
check("POST from a foreign Origin is refused",
      get(method="POST", host="127.0.0.1:8765", origin="https://evil.example.com") == 403)
check("DELETE from a foreign Origin is refused",
      get(method="DELETE", host="127.0.0.1:8765", origin="https://evil.example.com") == 403)
check("POST from the HUD's own origin is allowed",
      get(method="POST", host="127.0.0.1:8765", origin="http://127.0.0.1:8765") == 200)
check("POST from the Vite dev server origin is allowed",
      get(method="POST", host="localhost:5173", origin="http://localhost:5173") == 200)
check("POST from a different loopback port is refused",
      get(method="POST", host="127.0.0.1:8765", origin="http://127.0.0.1:9999") == 403)
check("POST with Origin: null (sandboxed iframe, file://) is refused",
      get(method="POST", host="127.0.0.1:8765", origin="null") == 403)
check("a lookalike Origin is refused",
      get(method="POST", host="127.0.0.1:8765", origin="http://127.0.0.1:8765.evil.com") == 403)

print("== WebSocket ==")
check("the HUD's own origin can connect", ws_ok(host="127.0.0.1:8765", origin="http://127.0.0.1:8765"))
check("no Origin (CLI client) can connect", ws_ok(host="127.0.0.1:8765"))
check("Vite dev origin can connect", ws_ok(host="localhost:5173", origin="http://localhost:5173"))
check("a website's origin is refused", not ws_ok(host="127.0.0.1:8765", origin="https://evil.example.com"))
check("Origin: null is refused", not ws_ok(host="127.0.0.1:8765", origin="null"))
check("DNS rebinding Host is refused", not ws_ok(host="evil.example.com:8765", origin="http://evil.example.com:8765"))
check("a different loopback port is refused", not ws_ok(host="127.0.0.1:8765", origin="http://localhost:3000"))

print("== the real app is guarded ==")
import tempfile  # noqa: E402

from jarvis import config  # noqa: E402

config.DB_PATH = Path(tempfile.mkdtemp(prefix="jarvis-webguard-test-")) / "t.db"
from jarvis import web  # noqa: E402

real = TestClient(web.app, base_url="http://127.0.0.1:8765")
check("real app: foreign Host is refused on /api/tasks",
      real.get("/api/tasks", headers={"host": "evil.example.com"}).status_code == 403)
def _foreign_ws_refused():
    try:
        with real.websocket_connect("/ws", headers={"origin": "https://evil.example.com"}):
            return False
    except WebSocketDisconnect:
        return True


check("real app: foreign Origin cannot open /ws (refused before accept)", _foreign_ws_refused())
check("real app: foreign Origin cannot POST a task",
      real.post("/api/tasks", json={"title": "x"}, headers={"origin": "https://evil.example.com"}).status_code == 403)

print("ALL {} CHECKS PASSED".format(len(PASS)))

"""Small local ASGI runner using only Python's standard library."""
from __future__ import annotations

import asyncio
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from app.main import app
from app.config import NASA_API_KEY


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format, *_args):
        # Keep request URLs and query strings out of terminal logs.
        return

    def do_GET(self):
        self._serve()

    def do_POST(self):
        self._serve()

    def do_PUT(self):
        self._serve()

    def do_DELETE(self):
        self._serve()

    def _serve(self):
        body = self.rfile.read(int(self.headers.get("content-length", "0")))
        sent = []
        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        parsed = urlsplit(self.path)
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": self.command,
            "scheme": "http", "path": parsed.path,
            "raw_path": parsed.path.encode("utf-8"), "query_string": parsed.query.encode("ascii"),
            "root_path": "", "headers": [(key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in self.headers.items()],
            "server": self.server.server_address, "client": self.client_address,
        }
        try:
            asyncio.run(app(scope, receive, send))
            start = next(message for message in sent if message["type"] == "http.response.start")
            chunks = [message.get("body", b"") for message in sent if message["type"] == "http.response.body"]
            self.send_response(start["status"])
            headers = dict(start.get("headers", []))
            for key, value in headers.items():
                if key.lower() not in (b"connection", b"transfer-encoding"):
                    self.send_header(key.decode("latin-1"), value.decode("latin-1"))
            self.send_header("Content-Length", str(sum(map(len, chunks))))
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk)
        except Exception:
            details = traceback.format_exc()
            if NASA_API_KEY and NASA_API_KEY != "DEMO_KEY":
                details = details.replace(NASA_API_KEY, "[redacted]")
            print(details, file=sys.stderr, flush=True)
            self.send_error(500, "Local application error")
        finally:
            self.close_connection = True


if __name__ == "__main__":
    host = os.getenv("CAIRN_HOST", "127.0.0.1")
    port = int(os.getenv("CAIRN_PORT", "8000"))
    print(f"Cairn local server listening at http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()

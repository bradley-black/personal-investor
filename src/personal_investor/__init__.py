"""Personal Investor: serve the interactive investment planner locally."""

import argparse
import http.server
import json
import urllib.parse
import webbrowser
from pathlib import Path

from .quotes import get_canada_yields, get_quotes

STATIC_DIR = Path(__file__).parent / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the static page plus a small JSON API for live market data."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        if url.path == "/api/quotes":
            symbols = urllib.parse.parse_qs(url.query).get("symbols", [""])[0].split(",")
            self._json(get_quotes(symbols))
        elif url.path == "/api/yields":
            self._json(get_canada_yields())
        else:
            super().do_GET()

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Personal Investor planner.")
    parser.add_argument("--port", type=int, default=8000, help="port to serve on (default: 8000)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()

    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}/"
        print(f"Personal Investor running at {url}  (Ctrl+C to stop)")
        if not args.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")

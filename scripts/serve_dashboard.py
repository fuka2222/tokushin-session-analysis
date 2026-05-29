#!/usr/bin/env python3
"""ダッシュボードをローカルで表示（http://localhost:8765）。"""
import http.server
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
PORT = 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD), **kwargs)


def main() -> None:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"ダッシュボード: http://localhost:{PORT}")
        print("終了: Ctrl+C")
        httpd.serve_forever()


if __name__ == "__main__":
    main()

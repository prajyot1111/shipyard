"""The reports HTTP API, standard library only."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from reports.search import search
from reports.store import all_reports, by_id


def as_dict(report) -> dict:
    return {"id": report.id, "title": report.title, "owner": report.owner,
            "created": report.created.isoformat(), "total": report.total}


def reports_for(query: dict) -> list[dict]:
    words = (query.get("q") or [""])[0]
    found = search(words) if words else all_reports()
    return [as_dict(r) for r in found]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if parts == ["reports"]:
            return self.send(200, reports_for(parse_qs(url.query)))
        if len(parts) == 2 and parts[0] == "reports" and parts[1].isdigit():
            report = by_id(int(parts[1]))
            return self.send(200, as_dict(report)) if report else self.send(404, {"error": "no such report"})
        return self.send(404, {"error": "not found"})

    def send(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()

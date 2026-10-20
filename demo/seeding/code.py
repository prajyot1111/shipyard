"""The code on the seeded branches: each one a commit on a repo of the sandbox, by whoever
wrote it, pushed to the bare origin before its pull request is opened.

A finding on a review card points at a line of these files, found by `line_of` so an edit
here moves the finding with it.
"""

SEARCH_FIX = {
    "repo": "api", "branch": "bug/st-98/fix-search-ignoring-case", "author": "Robin",
    "subject": "Fix search ignoring case",
    "files": {
        "reports/search.py": '''"""Search over report titles."""

from reports.store import Report, all_reports


def search(query: str) -> list[Report]:
    words = query.casefold().split()
    return [r for r in all_reports() if all(word in r.title.casefold() for word in words)]
''',
        "tests/test_search_case.py": '''import unittest

from reports.search import search


class SearchCaseTest(unittest.TestCase):
    def test_search_ignores_case(self):
        self.assertEqual([r.id for r in search("revenue")], [1, 4])


if __name__ == "__main__":
    unittest.main()
''',
    },
}

DATE_FILTER = {
    "repo": "api", "branch": "feature/date-range-filter", "author": "Maya Chen",
    "subject": "Add a date range filter to /reports",
    "files": {
        "reports/dates.py": '''"""Filter reports by the day they were created."""

from datetime import date

from reports.store import Report


def parse_day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def in_range(reports: list[Report], start: str | None, end: str | None) -> list[Report]:
    first, last = parse_day(start), parse_day(end)
    return [r for r in reports
            if (first is None or r.created >= first) and (last is None or r.created < last)]
''',
        "reports/app.py": '''"""The reports HTTP API, standard library only."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from reports.dates import in_range
from reports.search import search
from reports.store import all_reports, by_id


def as_dict(report) -> dict:
    return {"id": report.id, "title": report.title, "owner": report.owner,
            "created": report.created.isoformat(), "total": report.total}


def reports_for(query: dict) -> list[dict]:
    words = (query.get("q") or [""])[0]
    found = search(words) if words else all_reports()
    start, end = (query.get("from") or [None])[0], (query.get("to") or [None])[0]
    if start or end:
        found = in_range(found, start, end)
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
''',
        "tests/test_dates.py": '''import unittest

from reports.app import reports_for


class DateRangeTest(unittest.TestCase):
    def test_from_keeps_later_reports(self):
        found = reports_for({"from": ["2026-09-01"]})
        self.assertEqual([r["id"] for r in found], [3, 4, 5])


if __name__ == "__main__":
    unittest.main()
''',
    },
}

TOTALS = {
    "repo": "web", "branch": "feature/table-totals", "author": "Tom Okafor",
    "subject": "Show report totals in the table footer",
    "files": {
        "index.html": '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reports</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>Reports</h1>
  <input id="search" type="search" placeholder="Search reports">
  <table id="reports">
    <thead><tr><th>Title</th><th>Owner</th><th>Created</th><th>Total</th></tr></thead>
    <tbody></tbody>
    <tfoot><tr><td colspan="3">Total</td><td></td></tr></tfoot>
  </table>
  <script src="reports.js"></script>
</body>
</html>
''',
        "reports.js": '''// The reports page: fetch the list from the api and draw it as a table.
const API = "http://127.0.0.1:8000";

async function load(query) {
  const url = query ? `${API}/reports?q=${encodeURIComponent(query)}` : `${API}/reports`;
  const response = await fetch(url);
  return response.json();
}

function draw(reports) {
  const body = document.querySelector("#reports tbody");
  body.innerHTML = "";
  for (const report of reports) {
    const row = document.createElement("tr");
    for (const value of [report.title, report.owner, report.created, report.total]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    }
    body.appendChild(row);
  }
  drawTotal(reports);
}

function drawTotal(reports) {
  const total = reports.reduce((sum, report) => sum + report.total, 0);
  document.querySelector("#reports tfoot td:last-child").textContent = total;
}

document.querySelector("#search").addEventListener("input", async (event) => {
  draw(await load(event.target.value));
});

load("").then(draw);
''',
    },
}

CACHE_WEB = {
    "repo": "web", "branch": "feature/st-104/cache-report-queries", "author": "Robin",
    "subject": "Say how fresh the reports list is",
    "files": {
        "fresh.js": '''// Under the table: when the list was loaded, since the api caches it for a minute.
const loaded = new Date();
document.querySelector("#reports").insertAdjacentHTML(
  "afterend", `<p class="fresh">Loaded at ${loaded.toLocaleTimeString()}</p>`);
''',
    },
}

CACHE = {
    "repo": "api", "branch": "feature/st-104/cache-report-queries", "author": "Robin",
    "subject": "Cache the reports list for a minute",
    "files": {
        "reports/cache.py": '''"""A small time-boxed cache for the reports list."""

import time

SECONDS = 60
_kept: dict[str, tuple[float, list]] = {}


def cached(key: str, load) -> list:
    now = time.monotonic()
    hit = _kept.get(key)
    if hit and now - hit[0] < SECONDS:
        return hit[1]
    value = load()
    _kept[key] = (now, value)
    return value
''',
    },
}

# The export card's change (scene 8), one commit per repo on the card's own branch.
EXPORT = {
    "api": {
        "subject": "Stream the reports as CSV at /reports.csv",
        "files": {
            "reports/app.py": '''"""The reports HTTP API, standard library only."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from reports.export import rows
from reports.search import search
from reports.store import all_reports, by_id


def as_dict(report) -> dict:
    return {"id": report.id, "title": report.title, "owner": report.owner,
            "created": report.created.isoformat(), "total": report.total}


def found_for(query: dict) -> list:
    words = (query.get("q") or [""])[0]
    return search(words) if words else all_reports()


def reports_for(query: dict) -> list[dict]:
    return [as_dict(r) for r in found_for(query)]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if parts == ["reports"]:
            return self.send(200, reports_for(parse_qs(url.query)))
        if parts == ["reports.csv"]:
            return self.stream_csv(found_for(parse_qs(url.query)))
        if len(parts) == 2 and parts[0] == "reports" and parts[1].isdigit():
            report = by_id(int(parts[1]))
            return self.send(200, as_dict(report)) if report else self.send(404, {"error": "no such report"})
        return self.send(404, {"error": "not found"})

    def stream_csv(self, reports) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="reports.csv"')
        self.end_headers()
        for line in rows(reports):
            self.wfile.write(line.encode())

    def send(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
''',
            "reports/export.py": '''"""The reports as CSV, streamed a row at a time so a long list never sits in memory."""

import csv
import io

COLUMNS = ("id", "title", "owner", "created", "total")


def rows(reports):
    """Yield the CSV text line by line: the header, then one line per report."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for report in reports:
        writer.writerow((report.id, report.title, report.owner, report.created.isoformat(), report.total))
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
    if buffer.getvalue():
        yield buffer.getvalue()
''',
            "tests/test_export.py": '''import unittest

from reports.export import rows
from reports.store import all_reports


class ExportTest(unittest.TestCase):
    def test_header_then_a_line_per_report(self):
        text = "".join(rows(all_reports()))
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "id,title,owner,created,total")
        self.assertEqual(len(lines), 6)

    def test_titles_with_commas_are_quoted(self):
        from reports.store import Report
        from datetime import date
        text = "".join(rows([Report(9, "Revenue, by week", "Maya", date(2026, 9, 1), 5)]))
        self.assertIn('"Revenue, by week"', text)


if __name__ == "__main__":
    unittest.main()
''',
        },
    },
    "web": {
        "subject": "Add an Export CSV button to the reports page",
        "files": {
            "index.html": '''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reports</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <h1>Reports</h1>
  <input id="search" type="search" placeholder="Search reports">
  <button id="export" type="button">Export CSV</button>
  <table id="reports">
    <thead><tr><th>Title</th><th>Owner</th><th>Created</th><th>Total</th></tr></thead>
    <tbody></tbody>
  </table>
  <script src="reports.js"></script>
  <script src="export.js"></script>
</body>
</html>
''',
            "export.js": '''// The Export CSV button: download what the table shows, searched or not.
document.querySelector("#export").addEventListener("click", () => {
  const query = document.querySelector("#search").value;
  const url = `${API}/reports.csv${query ? `?q=${encodeURIComponent(query)}` : ""}`;
  window.location.assign(url);
});
''',
        },
    },
}


def line_of(text: str, needle: str) -> int:
    """The 1-based line of the first line containing `needle`."""
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    raise ValueError(f"{needle!r} is not in the text")

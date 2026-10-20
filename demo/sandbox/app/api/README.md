# reports api

A tiny reports service: `python3 -m reports.app` serves `/reports` on port 8000.

- `GET /reports` lists every report.
- `GET /reports?q=<words>` searches titles.
- `GET /reports/<id>` is one report.

Tests: `python3 -m unittest`.

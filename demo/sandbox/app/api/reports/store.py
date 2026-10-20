"""The reports, kept in memory: enough for the web page and the tests."""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Report:
    id: int
    title: str
    owner: str
    created: date
    total: int


REPORTS = [
    Report(1, "Monthly revenue", "Maya", date(2026, 8, 1), 48210),
    Report(2, "Churn by region", "Tom", date(2026, 8, 14), 312),
    Report(3, "Support backlog", "Ines", date(2026, 9, 2), 87),
    Report(4, "Revenue forecast", "Maya", date(2026, 9, 10), 51900),
    Report(5, "Signups by channel", "Arjun", date(2026, 9, 21), 1204),
]


def all_reports() -> list[Report]:
    return list(REPORTS)


def by_id(report_id: int) -> Report | None:
    return next((r for r in REPORTS if r.id == report_id), None)

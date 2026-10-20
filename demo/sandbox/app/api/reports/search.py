"""Search over report titles."""

from reports.store import Report, all_reports


def search(query: str) -> list[Report]:
    words = query.split()
    return [r for r in all_reports() if all(word in r.title for word in words)]

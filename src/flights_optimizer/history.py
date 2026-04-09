from __future__ import annotations

import json
from pathlib import Path

from .trip_optimizer import SearchReport


def save_report(report: SearchReport) -> Path:
    root = _history_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{report.search_id}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    (_history_root().parent / "last-search.txt").write_text(report.search_id, encoding="utf-8")
    return path


def load_report(search_id: str | None = None) -> SearchReport:
    target = search_id or last_search_id()
    if target is None:
        raise ValueError("no saved searches yet")
    path = _history_root() / f"{target}.json"
    if not path.exists():
        raise ValueError(f"saved search not found: {target}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SearchReport.from_dict(payload)


def list_reports(limit: int = 10) -> list[SearchReport]:
    root = _history_root()
    if not root.exists():
        return []
    reports: list[SearchReport] = []
    for path in sorted(root.glob("*.json"), reverse=True)[:limit]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports.append(SearchReport.from_dict(payload))
    return reports


def last_search_id() -> str | None:
    marker = _history_root().parent / "last-search.txt"
    if not marker.exists():
        return None
    value = marker.read_text(encoding="utf-8").strip()
    return value or None


def _history_root() -> Path:
    return Path.home() / ".flights-optimizer" / "searches"

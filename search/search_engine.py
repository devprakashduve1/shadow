"""Keyword / date / source search over DataLogger entries, with CSV export."""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

from logger.data_logger import DataLogger, LogEntry


class SearchEngine:
    def __init__(self, logger: Optional[DataLogger] = None, base_dir: str = "output/logs"):
        self.logger = logger or DataLogger(base_dir=base_dir)

    def search(
        self,
        keyword: Optional[str] = None,
        source: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[LogEntry]:
        matches: List[LogEntry] = []
        for entry in self.logger.iter_entries():
            entry_dt = datetime.fromisoformat(entry.timestamp)
            entry_date = entry_dt.date()

            if start_date and entry_date < start_date:
                continue
            if end_date and entry_date > end_date:
                continue
            if source and entry.source != source:
                continue
            if keyword and keyword.lower() not in entry.text.lower():
                continue

            matches.append(entry)
        return matches

    def export_csv(self, entries: List[LogEntry], path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "source", "text"])
            for entry in entries:
                writer.writerow([entry.timestamp, entry.source, entry.text])
        return path

"""SQLite record of every job found and what happened with it."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .search import Job

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "jobs.db"
STATUSES = ["new", "queued", "applied", "skipped", "interview", "offer", "rejected"]


class Tracker:
    def __init__(self, path: Path | str = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                found_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            )"""
        )
        self.conn.commit()

    def add_jobs(self, jobs: list[Job]) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        added = 0
        for job in jobs:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO jobs (id, data, status, found_at, updated_at) VALUES (?,?,?,?,?)",
                (job.id, json.dumps(job.to_dict()), "new", now, now),
            )
            added += cur.rowcount
        self.conn.commit()
        return added

    def set_status(self, job_id: str, status: str, notes: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(status)
        now = datetime.now().isoformat(timespec="seconds")
        if notes is None:
            self.conn.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, now, job_id))
        else:
            self.conn.execute(
                "UPDATE jobs SET status=?, notes=?, updated_at=? WHERE id=?", (status, notes, now, job_id)
            )
        self.conn.commit()

    def status_of(self, job_id: str) -> str | None:
        row = self.conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["status"] if row else None

    def rows(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM jobs"
        args: tuple = ()
        if status:
            sql += " WHERE status=?"
            args = (status,)
        sql += " ORDER BY updated_at DESC"
        out = []
        for r in self.conn.execute(sql, args):
            d = json.loads(r["data"])
            d.update(status=r["status"], found_at=r["found_at"], updated_at=r["updated_at"], notes=r["notes"])
            out.append(d)
        return out

    def counts(self) -> dict[str, int]:
        res = {s: 0 for s in STATUSES}
        for r in self.conn.execute("SELECT status, COUNT(*) c FROM jobs GROUP BY status"):
            res[r["status"]] = r["c"]
        return res

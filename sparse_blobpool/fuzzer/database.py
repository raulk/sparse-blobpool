"""SQLite database for fuzzer runs storage."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    seed INTEGER NOT NULL,
    scenario TEXT NOT NULL,
    status TEXT NOT NULL,
    wall_clock_seconds REAL NOT NULL,
    simulated_seconds REAL NOT NULL,
    timestamp_start TEXT NOT NULL,
    timestamp_end TEXT NOT NULL,
    anomalies TEXT NOT NULL,  -- JSON array
    metrics TEXT NOT NULL,    -- JSON object
    config TEXT NOT NULL,     -- JSON object
    attack TEXT,              -- JSON object, nullable
    error TEXT,               -- nullable
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON runs(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_scenario ON runs(scenario);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp_start);
CREATE INDEX IF NOT EXISTS idx_runs_seed ON runs(seed);
"""


class RunsDatabase:
    """SQLite database for fuzzer runs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_run(self, run: dict[str, Any]) -> None:
        """Insert a single run into the database."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, seed, scenario, status,
                    wall_clock_seconds, simulated_seconds,
                    timestamp_start, timestamp_end,
                    anomalies, metrics, config, attack, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["seed"],
                    run.get("scenario", "BASELINE"),
                    run["status"],
                    run["wall_clock_seconds"],
                    run["simulated_seconds"],
                    run["timestamp_start"],
                    run["timestamp_end"],
                    json.dumps(run.get("anomalies", [])),
                    json.dumps(run.get("metrics", {})),
                    json.dumps(run.get("config", {})),
                    json.dumps(run["attack"]) if run.get("attack") else None,
                    run.get("error"),
                ),
            )

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a database row to a run dictionary."""
        return {
            "run_id": row["run_id"],
            "seed": row["seed"],
            "scenario": row["scenario"],
            "status": row["status"],
            "wall_clock_seconds": row["wall_clock_seconds"],
            "simulated_seconds": row["simulated_seconds"],
            "timestamp_start": row["timestamp_start"],
            "timestamp_end": row["timestamp_end"],
            "anomalies": json.loads(row["anomalies"]),
            "metrics": json.loads(row["metrics"]),
            "config": json.loads(row["config"]),
            "attack": json.loads(row["attack"]) if row["attack"] else None,
            "error": row["error"],
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a single run by ID."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._row_to_dict(row) if row else None

    def get_runs(
        self,
        limit: int = 100,
        offset: int = 0,
        status: str | None = None,
        scenario: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get runs with optional filtering."""
        query = "SELECT * FROM runs WHERE 1=1"
        params: list[Any] = []

        if status:
            query += " AND status = ?"
            params.append(status)
        if scenario:
            query += " AND scenario = ?"
            params.append(scenario)

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_stats(self) -> dict[str, Any]:
        """Get aggregated statistics."""
        with self._connect() as conn:
            # Total counts
            total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
            if total == 0:
                return {
                    "total_runs": 0,
                    "success_rate": 0,
                    "attention_rate": 0,
                    "error_rate": 0,
                    "runs_per_minute": 0,
                    "anomaly_distribution": {},
                    "scenario_distribution": {},
                }

            success = conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'success'").fetchone()[
                0
            ]
            attention = conn.execute(
                "SELECT COUNT(*) FROM runs WHERE status LIKE '%ATTENTION%'"
            ).fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM runs WHERE status = 'error'").fetchone()[0]

            # Runs per minute
            time_range = conn.execute(
                "SELECT MIN(timestamp_start), MAX(timestamp_end) FROM runs"
            ).fetchone()
            rpm = 0.0
            if time_range[0] and time_range[1]:
                start = datetime.fromisoformat(time_range[0])
                end = datetime.fromisoformat(time_range[1])
                minutes = (end - start).total_seconds() / 60
                if minutes > 0:
                    rpm = total / minutes

            # Scenario distribution
            scenarios = conn.execute(
                "SELECT scenario, COUNT(*) as cnt FROM runs GROUP BY scenario"
            ).fetchall()
            scenario_dist = {row["scenario"]: row["cnt"] for row in scenarios}

            # Anomaly distribution using SQLite json_each() for efficiency
            # Extract anomaly type (text before '=' or '(' delimiter) and count
            anomaly_rows = conn.execute(
                """
                SELECT
                    CASE
                        WHEN INSTR(value, '=') > 0
                        THEN SUBSTR(value, 1, INSTR(value, '=') - 1)
                        WHEN INSTR(value, '(') > 0
                        THEN SUBSTR(value, 1, INSTR(value, '(') - 1)
                        ELSE value
                    END as anomaly_type,
                    COUNT(*) as cnt
                FROM (SELECT id, anomalies FROM runs ORDER BY id DESC LIMIT 500) r,
                     json_each(r.anomalies)
                GROUP BY anomaly_type
                """
            ).fetchall()
            anomaly_counts = {row["anomaly_type"]: row["cnt"] for row in anomaly_rows}

            return {
                "total_runs": total,
                "success_rate": success / total,
                "attention_rate": attention / total,
                "error_rate": errors / total,
                "runs_per_minute": rpm,
                "anomaly_distribution": anomaly_counts,
                "scenario_distribution": scenario_dist,
            }

    def get_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get the most recent runs."""
        return self.get_runs(limit=limit, offset=0)

    def count_runs(self) -> int:
        """Get total number of runs."""
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def get_max_id(self) -> int:
        """Get the maximum internal ID (for polling)."""
        with self._connect() as conn:
            result = conn.execute("SELECT MAX(id) FROM runs").fetchone()[0]
            return result or 0

    def get_runs_since(self, since_id: int) -> list[dict[str, Any]]:
        """Get runs with internal ID greater than since_id (for polling)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE id > ? ORDER BY id ASC", (since_id,)
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]


def migrate_from_ndjson(ndjson_path: Path, db: RunsDatabase) -> int:
    """Migrate runs from NDJSON file to SQLite database.

    Returns number of runs migrated.
    """
    if not ndjson_path.exists():
        return 0

    count = 0
    with open(ndjson_path) as f:
        for line in f:
            if line.strip():
                run = json.loads(line)
                db.insert_run(run)
                count += 1

    return count


def main() -> None:
    """CLI for database operations."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Fuzzer database utilities")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("fuzzer_output"),
        help="Output directory containing runs.ndjson",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Migrate NDJSON to SQLite",
    )
    args = parser.parse_args()

    if args.migrate:
        db_path = args.output_dir / "runs.db"
        ndjson_path = args.output_dir / "runs.ndjson"

        db = RunsDatabase(db_path)
        existing = db.count_runs()

        if existing > 0:
            print(f"Database already contains {existing} runs")
            return

        if not ndjson_path.exists():
            print(f"NDJSON file not found: {ndjson_path}")
            return

        print(f"Migrating from {ndjson_path} to {db_path}...")
        count = migrate_from_ndjson(ndjson_path, db)
        print(f"Migrated {count} runs")


if __name__ == "__main__":
    main()

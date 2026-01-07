"""FastAPI backend for fuzzer monitoring dashboard."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

_background_tasks: set[asyncio.Task[None]] = set()


class RunSummary(BaseModel):
    run_id: str
    seed: int
    status: str
    anomalies: list[str]
    wall_clock_seconds: float
    simulated_seconds: float
    timestamp: datetime
    metrics: dict[str, Any]


class DashboardStats(BaseModel):
    total_runs: int
    success_rate: float
    attention_rate: float
    error_rate: float
    runs_per_minute: float
    anomaly_distribution: dict[str, int]
    recent_runs: list[RunSummary]


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections:
            with contextlib.suppress(Exception):
                await connection.send_text(message)


def create_app(output_dir: Path) -> FastAPI:
    app = FastAPI(title="Fuzzer Monitor API")
    manager = ConnectionManager()
    runs_file = output_dir / "runs.ndjson"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def watch_ndjson_file() -> None:
        last_position = 0
        while True:
            try:
                if runs_file.exists():
                    with open(runs_file) as f:
                        f.seek(last_position)
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                await manager.broadcast(
                                    json.dumps({"type": "new_run", "data": data})
                                )
                        last_position = f.tell()
            except Exception as e:
                print(f"Error watching file: {e}")
            await asyncio.sleep(1)

    @app.on_event("startup")
    async def startup_event() -> None:
        task = asyncio.create_task(watch_ndjson_file())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    def _parse_run(run: dict[str, Any]) -> RunSummary:
        return RunSummary(
            run_id=run["run_id"],
            seed=run["seed"],
            status=run["status"],
            anomalies=run.get("anomalies", []),
            wall_clock_seconds=run["wall_clock_seconds"],
            simulated_seconds=run["simulated_seconds"],
            timestamp=datetime.fromisoformat(run["timestamp_start"]),
            metrics=run.get("metrics", {}),
        )

    def _load_all_runs() -> list[dict[str, Any]]:
        if not runs_file.exists():
            return []
        with open(runs_file) as f:
            return [json.loads(line) for line in f if line.strip()]

    @app.get("/api/stats")
    async def get_stats() -> DashboardStats:
        runs = _load_all_runs()
        anomaly_counts: dict[str, int] = {}

        for run in runs:
            for anomaly in run.get("anomalies", []):
                marker = anomaly.split("(")[0] if "(" in anomaly else anomaly
                anomaly_counts[marker] = anomaly_counts.get(marker, 0) + 1

        total = len(runs)
        success_count = sum(1 for r in runs if r["status"] == "success")
        attention_count = sum(1 for r in runs if "ATTENTION" in r["status"])
        error_count = sum(1 for r in runs if r["status"] == "error")

        rpm = 0.0
        if len(runs) >= 2:
            first_ts = datetime.fromisoformat(runs[0]["timestamp_start"])
            last_ts = datetime.fromisoformat(runs[-1]["timestamp_end"])
            duration_minutes = (last_ts - first_ts).total_seconds() / 60
            if duration_minutes > 0:
                rpm = total / duration_minutes

        recent = [_parse_run(run) for run in runs[-20:]]

        return DashboardStats(
            total_runs=total,
            success_rate=success_count / total if total > 0 else 0,
            attention_rate=attention_count / total if total > 0 else 0,
            error_rate=error_count / total if total > 0 else 0,
            runs_per_minute=rpm,
            anomaly_distribution=anomaly_counts,
            recent_runs=recent,
        )

    @app.get("/api/runs")
    async def get_runs(limit: int = 100, offset: int = 0) -> list[RunSummary]:
        all_runs = _load_all_runs()
        return [_parse_run(run) for run in all_runs[offset : offset + limit]]

    @app.get("/api/run/{run_id}")
    async def get_run_details(run_id: str) -> dict[str, Any]:
        for run in _load_all_runs():
            if run["run_id"] == run_id:
                trace_dir = output_dir / run_id
                if trace_dir.exists():
                    config_file = trace_dir / "config.json"
                    metrics_file = trace_dir / "metrics.json"

                    if config_file.exists():
                        with open(config_file) as cf:
                            run["trace_config"] = json.load(cf)

                    if metrics_file.exists():
                        with open(metrics_file) as mf:
                            run["trace_metrics"] = json.load(mf)

                return run

        return {"error": "Run not found"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    @app.get("/api/stream")
    async def stream_events() -> StreamingResponse:
        async def event_generator():
            last_position = 0
            while True:
                if runs_file.exists():
                    with open(runs_file) as f:
                        f.seek(last_position)
                        for line in f:
                            if line.strip():
                                data = json.loads(line)
                                yield f"data: {json.dumps(data)}\n\n"
                        last_position = f.tell()
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


def run_server(output_dir: Path, host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    app = create_app(output_dir)
    print(f"Starting fuzzer monitor server at http://{host}:{port}")
    print(f"Watching: {output_dir}/runs.ndjson")
    uvicorn.run(app, host=host, port=port)

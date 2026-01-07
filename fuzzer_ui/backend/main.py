"""FastAPI backend for fuzzer monitoring dashboard."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Fuzzer Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str) -> None:
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass


manager = ConnectionManager()

# State
fuzzer_output_dir = Path(os.environ.get("FUZZER_OUTPUT_DIR", "fuzzer_output"))
runs_file = fuzzer_output_dir / "runs.ndjson"


async def watch_ndjson_file() -> None:
    """Watch the NDJSON file for new runs and broadcast updates."""
    last_position = 0

    while True:
        try:
            if runs_file.exists():
                with open(runs_file, "r") as f:
                    f.seek(last_position)
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            await manager.broadcast(json.dumps({
                                "type": "new_run",
                                "data": data
                            }))
                    last_position = f.tell()
        except Exception as e:
            print(f"Error watching file: {e}")

        await asyncio.sleep(1)


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(watch_ndjson_file())


@app.get("/api/stats")
async def get_stats() -> DashboardStats:
    """Get current dashboard statistics."""
    runs = []
    anomaly_counts: dict[str, int] = {}

    if runs_file.exists():
        with open(runs_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    runs.append(data)

                    # Count anomalies
                    for anomaly in data.get("anomalies", []):
                        marker = anomaly.split("(")[0] if "(" in anomaly else anomaly
                        anomaly_counts[marker] = anomaly_counts.get(marker, 0) + 1

    total = len(runs)
    success_count = sum(1 for r in runs if r["status"] == "success")
    attention_count = sum(1 for r in runs if "ATTENTION" in r["status"])
    error_count = sum(1 for r in runs if r["status"] == "error")

    # Calculate runs per minute from timestamps
    rpm = 0.0
    if len(runs) >= 2:
        first_ts = datetime.fromisoformat(runs[0]["timestamp_start"])
        last_ts = datetime.fromisoformat(runs[-1]["timestamp_end"])
        duration_minutes = (last_ts - first_ts).total_seconds() / 60
        if duration_minutes > 0:
            rpm = total / duration_minutes

    # Get recent runs
    recent = []
    for run in runs[-20:]:
        recent.append(RunSummary(
            run_id=run["run_id"],
            seed=run["seed"],
            status=run["status"],
            anomalies=run.get("anomalies", []),
            wall_clock_seconds=run["wall_clock_seconds"],
            simulated_seconds=run["simulated_seconds"],
            timestamp=datetime.fromisoformat(run["timestamp_start"]),
            metrics=run.get("metrics", {})
        ))

    return DashboardStats(
        total_runs=total,
        success_rate=success_count / total if total > 0 else 0,
        attention_rate=attention_count / total if total > 0 else 0,
        error_rate=error_count / total if total > 0 else 0,
        runs_per_minute=rpm,
        anomaly_distribution=anomaly_counts,
        recent_runs=recent
    )


@app.get("/api/runs")
async def get_runs(limit: int = 100, offset: int = 0) -> list[RunSummary]:
    """Get paginated list of runs."""
    runs = []

    if runs_file.exists():
        with open(runs_file, "r") as f:
            all_runs = [json.loads(line) for line in f if line.strip()]

            for run in all_runs[offset:offset + limit]:
                runs.append(RunSummary(
                    run_id=run["run_id"],
                    seed=run["seed"],
                    status=run["status"],
                    anomalies=run.get("anomalies", []),
                    wall_clock_seconds=run["wall_clock_seconds"],
                    simulated_seconds=run["simulated_seconds"],
                    timestamp=datetime.fromisoformat(run["timestamp_start"]),
                    metrics=run.get("metrics", {})
                ))

    return runs


@app.get("/api/run/{run_id}")
async def get_run_details(run_id: str) -> dict[str, Any]:
    """Get detailed information for a specific run."""
    if runs_file.exists():
        with open(runs_file, "r") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    if data["run_id"] == run_id:
                        # Load trace files if they exist
                        trace_dir = fuzzer_output_dir / run_id
                        if trace_dir.exists():
                            config_file = trace_dir / "config.json"
                            metrics_file = trace_dir / "metrics.json"

                            if config_file.exists():
                                with open(config_file) as cf:
                                    data["trace_config"] = json.load(cf)

                            if metrics_file.exists():
                                with open(metrics_file) as mf:
                                    data["trace_metrics"] = json.load(mf)

                        return data

    return {"error": "Run not found"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/stream")
async def stream_events() -> StreamingResponse:
    """Server-sent events endpoint as WebSocket alternative."""
    async def event_generator():
        last_position = 0
        while True:
            if runs_file.exists():
                with open(runs_file, "r") as f:
                    f.seek(last_position)
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            yield f"data: {json.dumps(data)}\n\n"
                    last_position = f.tell()
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
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
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sparse_blobpool.fuzzer.database import RunsDatabase, migrate_from_ndjson

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
    attack: dict[str, Any] | None = None
    scenario: str = "BASELINE"


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


def create_app(output_dir: Path, static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Fuzzer Monitor API")
    manager = ConnectionManager()

    # Initialize SQLite database
    db_path = output_dir / "runs.db"
    db = RunsDatabase(db_path)

    # Legacy migration from NDJSON (one-time, for existing data)
    ndjson_path = output_dir / "runs.ndjson"
    if db.count_runs() == 0 and ndjson_path.exists():
        print(f"Migrating existing runs from {ndjson_path} to SQLite...")
        count = migrate_from_ndjson(ndjson_path, db)
        print(f"Migrated {count} runs to SQLite database")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    index_html = static_dir / "index.html" if static_dir else None

    async def watch_database() -> None:
        """Poll SQLite database for new runs and broadcast to WebSocket clients."""
        last_id = db.get_max_id()
        while True:
            try:
                new_runs = db.get_runs_since(last_id)
                for run in new_runs:
                    await manager.broadcast(json.dumps({"type": "new_run", "data": run}))
                if new_runs:
                    last_id = db.get_max_id()
            except Exception as e:
                print(f"Error polling database: {e}")
            await asyncio.sleep(1)

    @app.on_event("startup")
    async def startup_event() -> None:
        task = asyncio.create_task(watch_database())
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
            attack=run.get("attack"),
            scenario=run.get("scenario", "BASELINE"),
        )

    @app.get("/api/stats")
    async def get_stats() -> DashboardStats:
        stats = db.get_stats()
        recent_runs = db.get_recent_runs(20)

        return DashboardStats(
            total_runs=stats["total_runs"],
            success_rate=stats["success_rate"],
            attention_rate=stats["attention_rate"],
            error_rate=stats["error_rate"],
            runs_per_minute=stats["runs_per_minute"],
            anomaly_distribution=stats["anomaly_distribution"],
            recent_runs=[_parse_run(run) for run in recent_runs],
        )

    @app.get("/api/runs")
    async def get_runs(limit: int = 100, offset: int = 0) -> list[RunSummary]:
        runs = db.get_runs(limit=limit, offset=offset)
        return [_parse_run(run) for run in runs]

    @app.get("/api/run/{run_id}")
    async def get_run_details(run_id: str) -> dict[str, Any]:
        run = db.get_run(run_id)
        if not run:
            return {"error": "Run not found"}

        # Check for additional trace files
        trace_dir = output_dir / run_id
        if trace_dir.exists():
            config_file = trace_dir / "config.json"
            metrics_file = trace_dir / "metrics.json"

            if config_file.exists():
                with open(config_file) as cf:
                    config_data = json.load(cf)
                    run["trace_config"] = config_data
                    if "attack" in config_data:
                        run["attack"] = config_data["attack"]

            if metrics_file.exists():
                with open(metrics_file) as mf:
                    metrics_data = json.load(mf)
                    run["trace_metrics"] = metrics_data
                    if "victim_metrics" in metrics_data:
                        run["victim_metrics"] = metrics_data["victim_metrics"]

        return run

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
            last_count = db.count_runs()
            while True:
                current_count = db.count_runs()
                if current_count > last_count:
                    # Get new runs
                    new_runs = db.get_runs(limit=current_count - last_count, offset=0)
                    for run in reversed(new_runs):
                        yield f"data: {json.dumps(run)}\n\n"
                    last_count = current_count
                await asyncio.sleep(1)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    if static_dir and static_dir.exists() and index_html and index_html.exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}")
        async def serve_spa(path: str) -> FileResponse:
            file_path = static_dir / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(index_html)

    return app


def _find_static_dir() -> Path | None:
    from pathlib import Path

    candidates = [
        Path.cwd() / "web" / "dist",
        Path(__file__).parent.parent.parent.parent / "web" / "dist",
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


def run_server(output_dir: Path, host: str = "0.0.0.0", port: int = 8000) -> None:
    import uvicorn

    static_dir = _find_static_dir()
    app = create_app(output_dir, static_dir=static_dir)

    print(f"Starting fuzzer monitor server at http://{host}:{port}")
    print(f"Watching: {output_dir}/runs.ndjson")
    if static_dir:
        print(f"Serving frontend from: {static_dir}")
    else:
        print("Frontend not found. Run 'cd web && pnpm build' to enable.")
    uvicorn.run(app, host=host, port=port)


def start_server_background(output_dir: Path, host: str = "0.0.0.0", port: int = 8000) -> None:
    import threading

    import uvicorn

    static_dir = _find_static_dir()
    app = create_app(output_dir, static_dir=static_dir)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if static_dir:
        print(f"Monitoring server started at http://{host}:{port} (frontend: {static_dir})")
    else:
        print(f"Monitoring server started at http://{host}:{port} (API only)")

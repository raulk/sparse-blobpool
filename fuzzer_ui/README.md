# Fuzzer Monitoring Dashboard

A minimalistic web UI for monitoring the sparse blobpool fuzzer in real-time.

## Architecture

```
┌──────────────────┐     WebSocket      ┌──────────────────┐
│                  │ ◄─────────────────► │                  │
│   React + Vite   │                     │  FastAPI Backend │
│   (TypeScript)   │     REST API        │    (Python)      │
│                  │ ◄─────────────────► │                  │
└──────────────────┘                     └──────────────────┘
        │                                         │
        │                                         │
        ▼                                         ▼
   [TanStack Query]                        [NDJSON Logs]
   [Tailwind CSS]                          [SQLite Cache]
   [Recharts]                              [AsyncIO]
```

## Tech Stack

### Backend (FastAPI)
- **FastAPI** - Modern async Python web framework
- **uvicorn** - ASGI server
- **WebSockets** - Real-time updates
- **SQLite** - Lightweight metrics cache
- **watchfiles** - Monitor NDJSON log files

### Frontend (React + Vite)
- **Vite** - Lightning-fast build tool
- **React 18** - UI framework with concurrent features
- **TypeScript** - Type safety
- **TanStack Query** - Data fetching and caching
- **Tailwind CSS** - Utility-first styling
- **Recharts** - Composable charting
- **Lucide React** - Modern icon set

## Features

1. **Real-time Metrics**
   - Live run status (success/attention/error)
   - Throughput (runs/minute)
   - Anomaly distribution
   - Success rate trends

2. **Run History**
   - Searchable/filterable table
   - Click to view details
   - Replay capability

3. **Anomaly Analysis**
   - Grouped by type
   - Frequency charts
   - Pattern detection

4. **Configuration Viewer**
   - Active fuzzer config
   - Parameter ranges
   - Thresholds

## Running

### Docker (Recommended)

```bash
cd fuzzer_ui
docker compose up -d
```

Access at http://localhost:3000

### Development Mode

Run backend and frontend in separate terminals:

```bash
# Terminal 1: Backend (from project root)
cd fuzzer_ui/backend
uv sync
uv run uvicorn main:app --reload --port 8000

# Terminal 2: Frontend (from project root)
cd fuzzer_ui/frontend
npm install
npm run dev
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173

### With Fuzzer

Run the fuzzer in a separate terminal to generate data:

```bash
# From project root
uv run fuzz --max-runs 100
```

The UI will automatically pick up new runs via WebSocket.
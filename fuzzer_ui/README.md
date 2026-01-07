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

## Quick Start

```bash
# Backend
cd fuzzer_ui/backend
uv add fastapi uvicorn websockets watchfiles aiosqlite
uv run uvicorn main:app --reload --port 8000

# Frontend
cd fuzzer_ui/frontend
npm create vite@latest . -- --template react-ts
npm install
npm install @tanstack/react-query recharts tailwindcss lucide-react
npm run dev
```

## Deployment

```bash
docker compose up -d
```

Access at http://localhost:3000
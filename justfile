# Fuzzer monitoring dashboard

# Build frontend
build-web:
    cd web && pnpm install && pnpm exec tsc && pnpm exec vite build

# Run dashboard server (builds frontend if needed)
serve: build-web
    uv run fuzz --serve

# Run fuzzer with dashboard
fuzz runs="100": build-web
    uv run fuzz --serve --max-runs {{runs}}

# Run continuous fuzzer with dashboard
fuzz-continuous: build-web
    uv run fuzz --serve --max-runs 1000

# Run indefinitely with dashboard
fuzz-forever: build-web
    uv run fuzz --serve

# --- Docker ---

# Build Docker images
docker-build:
    sudo docker compose build

# Build and run containerized fuzzer with dashboard
server: docker-build
    sudo docker compose up -d

# Stop the server
server-stop:
    sudo docker compose down

# View server logs
server-logs:
    sudo docker compose logs -f

# Build and run with trace-all (saves all run traces)
server-trace: docker-build
    sudo FUZZER_ARGS="--trace-all" docker compose up -d

# --- Development ---

# Run frontend dev server (hot reload, proxies to port 8000)
dev-web:
    cd web && pnpm install && pnpm dev

# Run API server only
dev-api:
    uv run fuzz --serve

# --- Database ---

# Migrate NDJSON to SQLite
migrate-db:
    uv run python -m sparse_blobpool.fuzzer.database --migrate

# --- Testing ---

test:
    uv run pytest

lint:
    uv run ruff format .
    uv run ruff check . --fix

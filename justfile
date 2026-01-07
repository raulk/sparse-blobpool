# Fuzzer monitoring dashboard

image := "sparse-blobpool-fuzzer"
docker := "sudo docker"

# Build Docker image
build:
    {{docker}} build -t {{image}} .

# Run dashboard server only
serve: build
    {{docker}} run --rm -it -p 8000:8000 -v ./fuzzer_output:/app/fuzzer_output {{image}}

# Run fuzzer with dashboard
fuzz runs="100": build
    {{docker}} run --rm -it -p 8000:8000 -v ./fuzzer_output:/app/fuzzer_output {{image}} \
        uv run fuzz --serve --max-runs {{runs}}

# Run continuous fuzzer with dashboard
fuzz-continuous: build
    {{docker}} run --rm -it -p 8000:8000 -v ./fuzzer_output:/app/fuzzer_output {{image}} \
        uv run fuzz --serve --max-runs 1000

# Run indefinitely with dashboard (Ctrl+C to stop)
fuzz-forever: build
    {{docker}} run --rm -it -p 8000:8000 -v ./fuzzer_output:/app/fuzzer_output {{image}} \
        uv run fuzz --serve

# --- Local development (no Docker) ---

# Build frontend locally
build-web:
    cd web && pnpm install && pnpm exec tsc && pnpm exec vite build

# Run server locally (requires built frontend)
dev: build-web
    uv run fuzz --serve

# Run frontend dev server (hot reload, proxies API to port 8000)
dev-web:
    cd web && pnpm install && pnpm dev

# Run API server only (no frontend)
dev-api:
    uv run fuzz --serve

# --- Testing ---

# Run tests
test:
    uv run pytest

# Format and lint
lint:
    uv run ruff format .
    uv run ruff check . --fix

# Fuzzer monitoring dashboard

# Build the frontend
build-web:
    cd web && pnpm install && pnpm exec tsc && pnpm exec vite build

# Run fuzzer with monitoring dashboard (requires built frontend)
fuzz-serve:
    uv run fuzz --serve

# Build frontend and run fuzzer with dashboard
fuzz-ui: build-web
    uv run fuzz --serve

# Run continuous fuzzer with dashboard
fuzz-continuous: build-web
    uv run fuzz --serve --max-runs 1000

# Run fuzzer with specific run count and dashboard
fuzz-n runs="100": build-web
    uv run fuzz --serve --max-runs {{runs}}

# Development: run frontend dev server (API proxy to port 8000)
dev-web:
    cd web && pnpm install && pnpm dev

# Development: run API server only
dev-api:
    uv run fuzz --serve

# Run tests
test:
    uv run pytest

# Format and lint
lint:
    uv run ruff format .
    uv run ruff check . --fix

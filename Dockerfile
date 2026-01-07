# Build frontend
FROM node:20-alpine AS frontend-builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app/web
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm exec tsc && pnpm exec vite build

# Runtime
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --extra serve

# Copy application
COPY sparse_blobpool/ ./sparse_blobpool/

# Copy built frontend
COPY --from=frontend-builder /app/web/dist ./web/dist

# Create output directory
RUN mkdir -p fuzzer_output

EXPOSE 8000

# Default: run server only
CMD ["uv", "run", "fuzz", "--serve"]

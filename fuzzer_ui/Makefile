.PHONY: dev dev-backend dev-frontend build run stop clean

# Development
dev: dev-backend dev-frontend

dev-backend:
	cd backend && \
	uv pip install --system fastapi uvicorn websockets watchfiles aiosqlite && \
	uv run uvicorn main:app --reload --port 8000

dev-frontend:
	cd frontend && \
	npm install && \
	npm run dev

# Docker
build:
	docker-compose build

run:
	docker-compose up -d

stop:
	docker-compose down

logs:
	docker-compose logs -f

# Production
deploy: build
	docker-compose up -d --force-recreate

# Utilities
clean:
	docker-compose down -v
	rm -rf frontend/node_modules
	rm -rf frontend/dist
	rm -rf backend/__pycache__
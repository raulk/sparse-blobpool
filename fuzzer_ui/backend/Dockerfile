FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependencies file
COPY pyproject.toml .

# Install dependencies
RUN uv pip install --system fastapi uvicorn websockets watchfiles aiosqlite

# Copy application
COPY main.py .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
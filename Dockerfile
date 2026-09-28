# PaperMind Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock ./
COPY papermind/ ./papermind/
COPY prompts/ ./prompts/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create data directories
RUN mkdir -p /app/data/uploads /app/data/cache/parsed /app/data/chroma /app/data/exports

# Set environment
ENV PYTHONPATH=/app
ENV CHROMA_PERSIST_DIR=/app/data/chroma
ENV DATABASE_URL=postgresql://postgres:postgres@db:5432/papermind

# Expose port
EXPOSE 8000

# Run with uvicorn
CMD ["uv", "run", "uvicorn", "papermind.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
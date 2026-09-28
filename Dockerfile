# PaperMind Dockerfile - Multi-stage build for smaller image
# Build stage
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy project files
COPY pyproject.toml uv.lock README.md ./
COPY papermind/ ./papermind/
COPY prompts/ ./prompts/

# Install all dependencies (including chainlit for API)
RUN uv sync --frozen --no-dev

# Runtime stage
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install only runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/papermind /app/papermind
COPY --from=builder /app/prompts /app/prompts
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

# Create data directories
RUN mkdir -p /app/data/uploads /app/data/cache/parsed /app/data/chroma /app/data/exports

# Set environment
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"
ENV CHROMA_PERSIST_DIR=/app/data/chroma
ENV DATABASE_URL=postgresql://postgres:postgres@db:5432/papermind

# Expose ports
EXPOSE 8000 8001

# Default command runs API
CMD ["/app/.venv/bin/uvicorn", "papermind.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
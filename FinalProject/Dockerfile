# =============================================================================
# Multi-stage Dockerfile for Credit Default Risk Scoring API
# DDM501 - Group 5 Final Project
# =============================================================================

FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install astral uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency specifications
COPY pyproject.toml .python-version README.md ./

# Install dependencies using uv into system environment
ENV UV_SYSTEM_PYTHON=1
RUN uv pip install --system -r pyproject.toml

# Copy project code
COPY src/ ./src/
COPY app/ ./app/
COPY models/ ./models/
COPY data/ ./data/

# Environment settings
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

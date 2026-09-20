# =============================================================================
# Credit Default Risk Scoring API
# DDM501 - Lab 1: First ML Product
#
# TODO: Complete this Dockerfile.
# =============================================================================
FROM python:3.11-slim

# -----------------------------------------------------------------------------
# TODO 1: Set the environment variables
# -----------------------------------------------------------------------------
# Requirements:
#   PYTHONDONTWRITEBYTECODE=1   do not litter the image with .pyc files
#   PYTHONUNBUFFERED=1          flush stdout immediately, so `docker logs`
#                               shows output as it happens instead of when the
#                               buffer fills. Without this, a container that
#                               crashes often appears to have logged nothing.
#   PYTHONPATH=/app             so `from app.main import app` resolves
#
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# -----------------------------------------------------------------------------
# TODO 2: Set the working directory
# -----------------------------------------------------------------------------
# Hint: WORKDIR /app
WORKDIR /app

# -----------------------------------------------------------------------------
# TODO 3: Install dependencies
# -----------------------------------------------------------------------------
# Requirements:
#   - copy requirements.txt on its own FIRST, then run pip install,
#     then copy the source
#   - use pip install --no-cache-dir
#
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# TODO 4: Copy the application code
# -----------------------------------------------------------------------------
# Requirements: copy app/, scripts/ and data/
# Note we do NOT copy models/ — see docker-compose.yml for why.
COPY app/ app/
COPY scripts/ scripts/
COPY data/ data/

# -----------------------------------------------------------------------------
# TODO 5: Create and switch to a non-root user
# -----------------------------------------------------------------------------
# Requirements:
#   - create a user `appuser` with uid 1000 and a home directory
#   - create /app/models and give appuser ownership of /app
#   - switch to that user with USER
#
# A container running as root that gets compromised is a host running as root.
# This is three lines and it is not optional in production.
#
RUN useradd --uid 1000 --create-home appuser \
    && mkdir -p /app/models \
    && chown -R appuser /app
USER appuser

# -----------------------------------------------------------------------------
# TODO 6: Expose the port
# -----------------------------------------------------------------------------
# Hint: EXPOSE 8000
EXPOSE 8000

# -----------------------------------------------------------------------------
# TODO 7: Add a health check
# -----------------------------------------------------------------------------
# Requirements:
#   - check every 30s, time out after 10s, allow 10s of start-up, retry 3 times
#   - it must call GET /health AND check that model_loaded is true
#
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, json, sys; \
r = urllib.request.urlopen('http://localhost:8000/health'); \
d = json.loads(r.read()); \
sys.exit(0 if d.get('model_loaded') is True else 1)"

# -----------------------------------------------------------------------------
# TODO 8: Set the startup command
# -----------------------------------------------------------------------------
# Requirements: run uvicorn on app.main:app, bound to 0.0.0.0:8000
#
# Binding to 127.0.0.1 inside a container is a classic mistake: the service
# comes up, the logs look perfect, and nothing outside the container can reach
# it. Use 0.0.0.0.
#
# Hint: CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

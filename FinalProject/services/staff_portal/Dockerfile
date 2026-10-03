# syntax=docker/dockerfile:1.7
# =============================================================================
# Staff portal image (FastAPI + Jinja2 + HTMX, server-rendered, no CDN).
#
#   docker build -f services/staff_portal/Dockerfile -t credit-risk-staff-portal:dev .
#
# Build context: FinalProject/ (ignore rules: Dockerfile.dockerignore next to this
# file). The builder stage must stay byte-identical to deploy/docker/Dockerfile.api
# so all images share one BuildKit-cached dependency layer.
# =============================================================================

ARG PYTHON_IMAGE=python:3.11.16-slim-trixie@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e

# -----------------------------------------------------------------------------
# Stage 1 — builder: resolve and install locked dependencies into a venv.
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# The pip cache lives in a BuildKit cache mount, so it never lands in a layer.
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade "pip>=25.2" "setuptools>=78.1.1" "wheel>=0.46.2" \
    && pip install --requirement /tmp/requirements.txt

# The runtime never installs packages; dropping pip also drops its vendored libs.
RUN python -m pip uninstall --yes --quiet pip

# -----------------------------------------------------------------------------
# Stage 2 — runtime: venv + package + portal code + demo stream data, non-root.
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Must stay the first layer (same as Dockerfile.api) so the venv layer is shared.
COPY --from=builder /opt/venv /opt/venv

ARG APP_UID=10001
ARG APP_GID=10001

LABEL org.opencontainers.image.title="credit-risk-staff-portal" \
      org.opencontainers.image.description="Staff portal (customer service, risk analyst, system admin) for the Credit Default Risk Scoring API" \
      org.opencontainers.image.source="https://github.com/tungpheo11/DDM501_Group5"

RUN groupadd --system --gid "${APP_GID}" app \
    && useradd --system --uid "${APP_UID}" --gid app --create-home --home-dir /home/app \
       --shell /usr/sbin/nologin app \
    && python -m pip uninstall --yes --quiet setuptools wheel \
    && rm -rf /root/.cache

WORKDIR /app
COPY --chown=root:root --chmod=0755 src/ ./src/
COPY --chown=root:root --chmod=0755 configs/ ./configs/
COPY --chown=root:root --chmod=0755 services/staff_portal/ ./services/staff_portal/
COPY --chown=root:root --chmod=0755 data/processed/stream_normal.csv data/processed/stream_drifted.csv ./data/processed/

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src:/app/services \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=docker \
    CREDIT_RISK_HOME=/app \
    LOG_FORMAT=json \
    HOME=/home/app

USER app:app

EXPOSE 8030

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8030/health/ready', timeout=4)"]

# One process on purpose: the simulation job and the login throttle live in memory.
CMD ["uvicorn", "staff_portal.app:app", "--host", "0.0.0.0", "--port", "8030", "--workers", "1", "--proxy-headers", "--no-access-log"]

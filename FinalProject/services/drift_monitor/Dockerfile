# syntax=docker/dockerfile:1.7
# =============================================================================
# Drift monitor image (Evidently + PSI over the inference logs).
#
#   docker build -f services/drift_monitor/Dockerfile -t credit-risk-drift-monitor:dev .
#
# Build context: FinalProject/ (ignore rules: Dockerfile.dockerignore next to this
# file). The builder stage must stay byte-identical to deploy/docker/Dockerfile.api
# so both images share one BuildKit-cached dependency layer.
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
# Stage 2 — runtime: venv + package + service code + reference data, non-root.
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Must stay the first layer (same as Dockerfile.api) so the venv layer is shared.
COPY --from=builder /opt/venv /opt/venv

ARG APP_UID=10001
ARG APP_GID=10001

LABEL org.opencontainers.image.title="credit-risk-drift-monitor" \
      org.opencontainers.image.description="Evidently drift monitor for the Credit Default Risk Scoring API" \
      org.opencontainers.image.source="https://github.com/tungpheo11/DDM501_Group5"

RUN groupadd --system --gid "${APP_GID}" app \
    && useradd --system --uid "${APP_UID}" --gid app --create-home --home-dir /home/app \
       --shell /usr/sbin/nologin app \
    && python -m pip uninstall --yes --quiet setuptools wheel \
    && mkdir -p /var/lib/drift-monitor/reports \
    && chown -R app:app /var/lib/drift-monitor \
    && rm -rf /root/.cache

WORKDIR /app
COPY --chown=root:root --chmod=0755 src/ ./src/
COPY --chown=root:root --chmod=0755 configs/ ./configs/
COPY --chown=root:root --chmod=0755 models/ ./models/
COPY --chown=root:root --chmod=0755 services/drift_monitor/ ./services/drift_monitor/
COPY --chown=root:root --chmod=0755 data/reference/ ./data/reference/

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH=/app/src:/app/services \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=docker \
    CREDIT_RISK_HOME=/app \
    REPORTS_DIR=/var/lib/drift-monitor/reports \
    LOG_FORMAT=json \
    MPLBACKEND=Agg \
    HOME=/home/app

USER app:app

EXPOSE 8085

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health', timeout=4)"]

CMD ["uvicorn", "drift_monitor.app:app", "--host", "0.0.0.0", "--port", "8085", "--no-access-log"]

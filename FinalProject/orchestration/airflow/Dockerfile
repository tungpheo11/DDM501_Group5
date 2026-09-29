# syntax=docker/dockerfile:1.7
# =============================================================================
# Airflow 2.10 image for the credit-risk DAGs. Build context: FinalProject/.
#
#   docker build -f orchestration/airflow/Dockerfile -t credit-risk-airflow:dev .
#
# Two interpreters:
# * /opt/airflow-venv - Airflow itself, pinned by the official constraints file;
#   parses DAGs and runs the lightweight HTTP tasks.
# * /opt/venv - the project dependencies. The `builder` stage must stay
#   byte-identical to deploy/docker/Dockerfile.api, so this layer is the same
#   one the API and drift monitor images use (shared on disk, and ML tasks run
#   with exactly the serving dependency set). DAGs reach it through
#   @task.external_python(python=CREDIT_PYTHON).
# Airflow's own pins (SQLAlchemy 1.4, pandas < 3) conflict with the project's,
# which is why the two cannot share one environment.
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
# Stage 2 — Airflow in its own venv, constrained like the official image.
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS airflow-builder

ARG AIRFLOW_VERSION=2.10.5
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10 \
    PYTHONDONTWRITEBYTECODE=1

RUN python -m venv /opt/airflow-venv
COPY orchestration/airflow/constraints-3.11.txt /tmp/constraints-3.11.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/airflow-venv/bin/pip install "apache-airflow[postgres,statsd]==${AIRFLOW_VERSION}" \
      --constraint /tmp/constraints-3.11.txt \
    && /opt/airflow-venv/bin/airflow version

# -----------------------------------------------------------------------------
# Stage 3 — runtime.
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Must stay the first layer (same as Dockerfile.api) so the venv layer is shared.
COPY --from=builder /opt/venv /opt/venv

ARG AIRFLOW_UID=50000

LABEL org.opencontainers.image.title="credit-risk-airflow" \
      org.opencontainers.image.description="Airflow scheduler/webserver for the credit-risk retraining and monitoring DAGs" \
      org.opencontainers.image.source="https://github.com/tungpheo11/DDM501_Group5"

# libgomp1: OpenMP runtime for LightGBM/XGBoost (imported by credit_risk.training).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid "${AIRFLOW_UID}" --gid 0 --create-home --home-dir /home/airflow \
       --shell /bin/bash airflow \
    && mkdir -p /opt/airflow/logs /opt/airflow/orchestration /opt/credit_risk/data \
    && chown -R airflow:0 /opt/airflow /opt/credit_risk

COPY --from=airflow-builder /opt/airflow-venv /opt/airflow-venv
RUN echo "/opt/credit_risk/src" > /opt/venv/lib/python3.11/site-packages/credit_risk.pth

COPY --chown=airflow:0 src /opt/credit_risk/src
COPY --chown=airflow:0 configs /opt/credit_risk/configs
COPY --chown=airflow:0 models /opt/credit_risk/models
COPY --chown=airflow:0 data/manifest.json /opt/credit_risk/data/manifest.json
COPY --chown=airflow:0 data/reference /opt/credit_risk/data/reference
COPY --chown=airflow:0 data/processed /opt/credit_risk/data/processed
COPY --chown=airflow:0 --chmod=0755 orchestration/airflow/init_airflow.sh /opt/airflow/init_airflow.sh
COPY --chown=airflow:0 orchestration/airflow/utils /opt/airflow/orchestration/utils
COPY --chown=airflow:0 orchestration/airflow/dags /opt/airflow/orchestration/dags

ENV PATH="/opt/airflow-venv/bin:${PATH}" \
    AIRFLOW_HOME=/opt/airflow \
    AIRFLOW__CORE__DAGS_FOLDER=/opt/airflow/orchestration/dags \
    PYTHONPATH=/opt/airflow/orchestration \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CREDIT_PYTHON=/opt/venv/bin/python \
    CREDIT_RISK_HOME=/opt/credit_risk \
    APP_ENV=docker \
    MPLBACKEND=Agg

USER airflow
WORKDIR /opt/airflow
EXPOSE 8080 8974

ENTRYPOINT ["airflow"]
CMD ["version"]

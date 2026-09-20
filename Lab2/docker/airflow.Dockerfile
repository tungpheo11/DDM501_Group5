# =============================================================================
# Airflow image with the pipeline's dependencies
# DDM501 - Lab 2
# =============================================================================
FROM apache/airflow:2.8.4-python3.11

# -----------------------------------------------------------------------------
# TODO 1: Switch to the airflow user before installing
# -----------------------------------------------------------------------------
# The base image starts as root. pip install as root inside an Airflow image
# writes to the wrong site-packages and the scheduler will not see the packages.
USER airflow

# -----------------------------------------------------------------------------
# TODO 2: Install requirements-airflow.txt WITH Airflow's constraints file
# -----------------------------------------------------------------------------
COPY requirements-airflow.txt .
RUN pip install --no-cache-dir -r requirements-airflow.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.8.4/constraints-3.11.txt"

# -----------------------------------------------------------------------------
# TODO 3: Set PYTHONPATH so the DAG can import `pipeline`
# -----------------------------------------------------------------------------
# docker-compose.yml mounts ./pipeline to /opt/airflow/project/pipeline.
ENV PYTHONPATH=/opt/airflow/project
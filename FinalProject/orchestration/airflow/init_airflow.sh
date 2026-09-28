#!/usr/bin/env bash
# One-shot Airflow init: create the metadata database inside the shared
# Postgres, migrate the schema and create the admin user. Idempotent.
set -euo pipefail

: "${AIRFLOW_ADMIN_PASSWORD:?set AIRFLOW_ADMIN_PASSWORD in .env}"

# The Postgres volume may already be initialised (docker-entrypoint-initdb.d
# does not run again), so the airflow database is created here.
python - <<'PY'
import os

import psycopg2
from psycopg2 import sql

db_name = os.environ.get("AIRFLOW_DB_NAME", "airflow")
conn = psycopg2.connect(
    host=os.environ.get("POSTGRES_HOST", "postgres"),
    port=int(os.environ.get("POSTGRES_PORT_INTERNAL", "5432")),
    user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"],
    dbname=os.environ["POSTGRES_DB"],
)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    if cur.fetchone():
        print(f"Database '{db_name}' already exists")
    else:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
        print(f"Created database '{db_name}'")
conn.close()
PY

airflow db migrate

ADMIN_USER="${AIRFLOW_ADMIN_USER:-admin}"
if airflow users list --output plain 2>/dev/null | awk '{print $2}' | grep -qx "${ADMIN_USER}"; then
  echo "Admin user '${ADMIN_USER}' already exists"
else
  airflow users create \
    --username "${ADMIN_USER}" \
    --password "${AIRFLOW_ADMIN_PASSWORD}" \
    --firstname Admin \
    --lastname User \
    --role Admin \
    --email "${AIRFLOW_ADMIN_EMAIL:-admin@example.com}"
fi

echo "Airflow init completed"

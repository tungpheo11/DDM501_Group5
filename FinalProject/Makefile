# Credit Default Risk Scoring — developer entrypoints.
# Run `make help` for the list of targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON_VERSION ?= 3.11
VENV ?= .venv
BIN := $(VENV)/bin
PY := $(BIN)/python
UV := $(shell command -v uv 2>/dev/null)

COMPOSE_FILE ?= deploy/compose/docker-compose.yml
ENV_FILE ?= $(if $(wildcard .env),.env,.env.example)
COMPOSE_PROFILES ?= core,monitoring,orchestration
export COMPOSE_PROFILES
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

SIM_MODE ?= staged_progression
SIM_COUNT ?= 30
API_URL ?= http://localhost:18020

.PHONY: help setup lock lint format typecheck test test-unit test-integration test-e2e test-load test-load-stress test-cov \
        data manifest validate train retrain registry rollback mlflow-ui drift up down logs ps simulate evidence clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Create .venv and install the package (editable) with dev tools
ifdef UV
	uv sync --dev --python $(PYTHON_VERSION)
else
	python3 -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	$(BIN)/pip install -e . --no-deps
endif
	@test -f .env || cp .env.example .env
	@echo "Environment ready: source $(VENV)/bin/activate"

lock: ## Re-lock dependencies and regenerate requirements*.txt (needs uv)
	uv lock
	uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o requirements.txt
	{ echo "# Development/CI dependencies. Regenerate with: make lock"; echo "-r requirements.txt"; \
	  uv export --only-group dev --no-hashes --no-emit-project --format requirements-txt; } > requirements-dev.txt

lint: ## ruff + black --check + mypy
	$(BIN)/ruff check .
	$(BIN)/black --check .
	$(BIN)/mypy

format: ## Auto-fix lint issues and format code
	$(BIN)/ruff check --fix .
	$(BIN)/black .

typecheck: ## mypy only
	$(BIN)/mypy

test: ## Run the full test suite (hermetic, no Docker needed; e2e/load excluded)
	$(BIN)/pytest

test-unit: ## Unit tests only
	$(BIN)/pytest tests/unit

test-integration: ## Integration tests only
	$(BIN)/pytest tests/integration

test-e2e: ## End-to-end tests against the running stack (make up)
	$(BIN)/pytest tests/e2e -m e2e

test-load: ## Locust load test against the running API -> reports/load/ (LOAD_USERS, LOAD_DURATION, LOAD_P95_MS)
	$(BIN)/pytest tests/load -m load

test-load-stress: ## Capacity gate (ADR-0007): 20 users for 60 s, p95 <= 100 ms -> reports/load/locust_stress_*
	LOAD_USERS=20 LOAD_DURATION=60s LOAD_REPORT_NAME=locust_stress $(BIN)/pytest tests/load -m load

test-cov: ## Tests with coverage reports in reports/coverage/
	$(BIN)/pytest --cov --cov-report=term --cov-report=xml:reports/coverage/coverage.xml \
	  --cov-report=html:reports/coverage/html --junitxml=reports/coverage/junit.xml

data: ## Re-split data/raw into reference/processed partitions, then refresh the manifest
	$(PY) scripts/split_data.py
	$(MAKE) manifest

manifest: ## Regenerate data/manifest.json
	$(PY) scripts/build_data_manifest.py

$(PY):
	$(MAKE) setup

validate: $(PY) ## Validate every dataset (pandera + manifest hashes) -> reports/data_validation.json
	$(PY) scripts/validate_data.py

train: validate ## Tune 4 candidates (Optuna + 5-fold CV), gate, register @champion, write reports/model_comparison.*
	$(PY) scripts/train.py $(if $(N_TRIALS),--n-trials $(N_TRIALS),)

retrain: $(PY) ## Champion/challenger retraining with promotion + API hot reload
	$(PY) scripts/retrain.py

registry: $(PY) ## Show registered model versions and aliases
	$(PY) scripts/manage_registry.py show

rollback: $(PY) ## Move @champion back to @previous_champion (or VERSION=<n>)
	$(PY) scripts/manage_registry.py rollback $(if $(VERSION),--to-version $(VERSION),)

mlflow-ui: $(PY) ## Browse the local fallback MLflow store (mlruns/) on http://localhost:5001
	$(BIN)/mlflow ui --backend-store-uri sqlite:///mlruns/mlflow.db --port 5001

drift: ## PSI + Evidently drift report into reports/
	$(PY) scripts/detect_drift.py

up: ## Build + start the stack (COMPOSE_PROFILES, default all) and wait until every service is healthy
	@test -f .env || { cp .env.example .env; echo "Created .env from .env.example"; }
	$(COMPOSE) up -d --build --remove-orphans
	@$(MAKE) --no-print-directory health

up-core: ## Start only the core profile (postgres, minio, mlflow, api, staff-portal)
	@$(MAKE) --no-print-directory up COMPOSE_PROFILES=core

up-prod: ## Start the stack with the production overlay (127.0.0.1 ports, no source mounts)
	$(COMPOSE) -f deploy/compose/docker-compose.prod.yml up -d --build --remove-orphans
	@$(MAKE) --no-print-directory health COMPOSE="$(COMPOSE) -f deploy/compose/docker-compose.prod.yml"

health: ## Wait for all services to be healthy and print services + ports (HEALTH_TIMEOUT)
	@python3 scripts/check_stack_health.py --compose "$(COMPOSE)" --timeout $(or $(HEALTH_TIMEOUT),900)

down: ## Stop the Docker Compose stack (keeps volumes; `make down-v` wipes them)
	$(COMPOSE) down --remove-orphans

down-v: ## Stop the stack and delete its volumes (clean-machine reset)
	$(COMPOSE) down -v --remove-orphans

logs: ## Tail Compose logs (SERVICE=<name> for one service)
	$(COMPOSE) logs -f --tail=100 $(SERVICE)

ps: ## Show Compose service status
	$(COMPOSE) ps -a

# SCENARIO=normal|drift|attack|load|outage runs simulations/run_scenario.py;
# without SCENARIO the legacy persona simulator (SIM_MODE, SIM_COUNT) is used.
simulate: ## Traffic scenarios: make simulate SCENARIO=normal|drift|attack|load|outage [SIM_ARGS=...]
ifdef SCENARIO
	$(PY) simulations/run_scenario.py $(SCENARIO) --api-url $(API_URL) --env-file $(ENV_FILE) $(SIM_ARGS)
else
	$(PY) simulations/persona_simulator.py --mode $(SIM_MODE) --count $(SIM_COUNT) --api-url $(API_URL)
endif

# --- Platform & observability -------------------------------------------------
PROMETHEUS_IMAGE ?= prom/prometheus:v3.15.0
ALERTMANAGER_IMAGE ?= prom/alertmanager:v0.28.1
CHAOS_DIR := deploy/compose/chaos
AIRFLOW_EXEC = $(COMPOSE) exec -T airflow-scheduler

.PHONY: up-core up-prod health down-v config-check alerts-test dashboards dags-check dags-test \
        retrain-dag retrain-fail drift-dag chaos-api-down chaos-model-unloaded chaos-latency \
        chaos-drift-down chaos-drift-stale chaos-dag-import-error chaos-restore alerts alerts-send-test

config-check: ## Validate compose files (dev, prod, chaos overlays) and the Airflow DAGs import
	$(COMPOSE) config --quiet
	$(COMPOSE) -f deploy/compose/docker-compose.prod.yml config --quiet
	$(COMPOSE) -f $(CHAOS_DIR)/model-unloaded.yml config --quiet
	$(COMPOSE) -f $(CHAOS_DIR)/drift-db-unreachable.yml config --quiet
	@echo "compose config OK"

alerts-test: ## promtool check + unit tests (each alert fires and resolves); amtool check (webhook & Telegram modes)
	docker run --rm --user 0 -w /tmp --entrypoint promtool -v $(CURDIR)/monitoring/prometheus:/p:ro \
	  $(PROMETHEUS_IMAGE) check rules /p/rules/recording_rules.yml /p/rules/api_alerts.yml /p/rules/model_alerts.yml /p/rules/drift_alerts.yml
	docker run --rm --user 0 -w /tmp --entrypoint promtool -v $(CURDIR)/monitoring/prometheus:/p:ro \
	  $(PROMETHEUS_IMAGE) test rules /p/tests/alerts_test.yml
	@set -e; tmp=$$(mktemp -d); tpl=monitoring/alertmanager/alertmanager.yml.tmpl; \
	  sed -e '/# BEGIN_TELEGRAM/,/# END_TELEGRAM/d' $$tpl > $$tmp/webhook.yml; \
	  sed -e '/# BEGIN_TELEGRAM/d' -e '/# END_TELEGRAM/d' -e 's/__TELEGRAM_CHAT_ID__/-1001/' $$tpl > $$tmp/telegram.yml; \
	  mkdir -p $$tmp/tok && printf x > $$tmp/tok/telegram_bot_token; \
	  for mode in webhook telegram; do echo "==> amtool check-config ($$mode)"; \
	    docker run --rm --entrypoint amtool -v $$tmp:/cfg:ro -v $$tmp/tok:/tmp/alertmanager:ro \
	      -v $(CURDIR)/monitoring/alertmanager/templates:/etc/alertmanager/templates:ro \
	      $(ALERTMANAGER_IMAGE) check-config /cfg/$$mode.yml; done; rm -rf $$tmp

dashboards: $(PY) ## Regenerate Grafana dashboards JSON from scripts/build_grafana_dashboards.py
	$(PY) scripts/build_grafana_dashboards.py

dags-check: ## Parse Airflow DAGs inside the Airflow image (no import errors); list-import-errors if running
	$(COMPOSE) run --rm --no-deps --entrypoint python airflow-scheduler -m utils.check_dags
	@if [ -n "$$($(COMPOSE) ps -q airflow-scheduler 2>/dev/null)" ]; then \
	  $(AIRFLOW_EXEC) airflow dags list-import-errors; fi

dags-test: ## Run tests/unit/test_airflow_dags.py inside the Airflow image (pytest installed into /tmp)
	$(COMPOSE) run --rm --no-deps -v "$(CURDIR)/tests:/opt/tests:ro" --entrypoint sh airflow-scheduler -c \
	  "pip install -q --target /tmp/pt pytest && cd /opt && PYTHONPATH=/tmp/pt:/opt/airflow/orchestration \
	   python -m pytest tests/unit/test_airflow_dags.py -v -p no:cacheprovider --noconftest -o addopts='' -c /dev/null --rootdir=/opt"

retrain-dag: ## Trigger the model_retrain DAG (REASON=...)
	$(AIRFLOW_EXEC) airflow dags trigger model_retrain -c '{"reason": "$(or $(REASON),manual make retrain-dag)"}'

retrain-fail: ## Trigger model_retrain with an impossible ROC-AUC floor (fires RetrainFailed)
	$(AIRFLOW_EXEC) airflow dags trigger model_retrain -c '{"min_roc_auc": 0.99, "reason": "forced failure demo"}'

drift-dag: ## Trigger the drift_monitoring DAG now
	$(AIRFLOW_EXEC) airflow dags trigger drift_monitoring

chaos-api-down: ## Stop the API (APIDown after 1 min)
	$(COMPOSE) stop api

chaos-model-unloaded: ## Recreate the API with no loadable model (ModelNotLoaded; + traffic -> HighErrorRate)
	$(COMPOSE) -f $(CHAOS_DIR)/model-unloaded.yml up -d --no-deps api

chaos-latency: ## Throttle the API to 0.5 CPU (then `make simulate SCENARIO=load` -> HighLatencyP95)
	docker update --cpus 0.5 $$($(COMPOSE) ps -q api)

chaos-drift-down: ## Stop the drift monitor (DriftMonitorDown after 2 min)
	$(COMPOSE) stop drift-monitor

chaos-drift-stale: ## Drift monitor loses its database (DriftAnalysisStale after ~20 min)
	$(COMPOSE) -f $(CHAOS_DIR)/drift-db-unreachable.yml up -d --no-deps drift-monitor

chaos-dag-import-error: ## Drop a broken DAG file (AirflowDagImportErrors after ~5 min)
	@printf 'from airflow import DAG\nraise RuntimeError("chaos: broken DAG")\n' > orchestration/airflow/dags/_chaos_broken_dag.py
	@echo "wrote orchestration/airflow/dags/_chaos_broken_dag.py"

chaos-restore: ## Undo every chaos-* action (API, CPU, drift monitor, broken DAG)
	rm -f orchestration/airflow/dags/_chaos_broken_dag.py
	-docker update --cpus 2 $$($(COMPOSE) ps -q api)
	$(COMPOSE) up -d --no-deps api drift-monitor

alerts: ## Show firing alerts (Prometheus) and the last notifications received by the webhook
	@python3 -c "import json,urllib.request as u; \
	a=json.load(u.urlopen('http://localhost:$(or $(PROMETHEUS_PORT),19090)/api/v1/alerts'))['data']['alerts']; \
	print('Prometheus alerts:'); [print(f\"  {x['labels']['alertname']:<28} {x['state']:<8} {x['labels'].get('severity','')}\") for x in a] or print('  none'); \
	s=json.load(u.urlopen('http://localhost:$(or $(ALERT_WEBHOOK_PORT),19095)/alerts/state')); \
	print('Webhook receiver (last status per alert):'); [print(f\"  {x['alertname']:<28} {x['status']:<8} fired={x['fired']} resolved={x['resolved']}\") for x in s] or print('  none')"

alerts-send-test: ## Push a synthetic AlertmanagerTest alert to every receiver (FIRING now, RESOLVED ~2-3 min later)
	@python3 -c "import json,datetime as d,urllib.request as u; n=d.datetime.now(d.timezone.utc); \
	a=[{'labels':{'alertname':'AlertmanagerTest','severity':'warning','component':'alerting'}, \
	'annotations':{'summary':'Test notification from make alerts-send-test','description':'Synthetic alert used to check the notification channels; it resolves on its own after 2 minutes.', \
	'runbook_url':'https://github.com/tungpheo11/DDM501_Group5/blob/main/FinalProject/docs/runbooks/alerts.md'}, \
	'startsAt':n.isoformat(),'endsAt':(n+d.timedelta(minutes=2)).isoformat()}]; \
	u.urlopen(u.Request('http://localhost:$(or $(ALERTMANAGER_PORT),19093)/api/v2/alerts',json.dumps(a).encode(),{'Content-Type':'application/json'})); \
	print('AlertmanagerTest sent at', n.strftime('%Y-%m-%d %H:%M:%S UTC'), '- expect FIRING within ~15 s, RESOLVED within ~3 min')"

# --- Serving API --------------------------------------------------------------
API_IMAGE ?= credit-risk-api:dev
PORTAL_IMAGE ?= credit-risk-staff-portal:dev
# `make scan` scans API_IMAGE by default; scan-portal reuses it for PORTAL_IMAGE.
SCAN_IMAGE ?= $(API_IMAGE)
SCAN_REPORT ?= trivy-report.json
# Pinned by digest: mutable Trivy tags were hijacked in the March 2026 supply-chain incident.
TRIVY_IMAGE ?= aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
TRIVY_CACHE_DIR ?= $(HOME)/.cache/trivy
# Host-mounted TMPDIR: the exported image tarball (GBs) stays off the container's writable layer.
TRIVY_TMP_DIR ?= $(HOME)/.cache/trivy-tmp
TRIVY := docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v $(TRIVY_CACHE_DIR):/root/.cache/trivy \
	-v $(TRIVY_TMP_DIR):/trivy-tmp -e TMPDIR=/trivy-tmp -v $(CURDIR)/reports/security:/reports $(TRIVY_IMAGE)
BENCH_REQUESTS ?= 500

.PHONY: openapi serve serve-portal bench docker-build docker-build-portal scan scan-portal

openapi: ## Regenerate docs/openapi.yaml from the FastAPI app
	$(PY) scripts/export_openapi.py

serve: ## Run the API locally (one uvicorn process, auto-reload) on http://localhost:$(or $(API_PORT),18020)
	$(BIN)/uvicorn credit_risk.serving.app:app --reload --port $(or $(API_PORT),18020) --no-access-log

bench: ## p95 latency of POST /api/v1/predict against API_URL (fails above 100 ms)
	$(PY) scripts/benchmark_latency.py --api-url $(API_URL) --requests $(BENCH_REQUESTS) \
	  --output reports/latency_benchmark.json

serve-portal: ## Run the staff portal locally on http://localhost:$(or $(PORTAL_PORT),18030) against API_URL (auto-reload)
	set -a; . "$(abspath $(ENV_FILE))"; set +a; PORTAL_API_URL=$(or $(API_URL),http://localhost:18020) \
	  $(BIN)/uvicorn staff_portal.app:app --app-dir services --reload --port $(or $(PORTAL_PORT),18030) --no-access-log

docker-build: ## Build the API image (API_IMAGE)
	docker build -f deploy/docker/Dockerfile.api -t $(API_IMAGE) .

docker-build-portal: ## Build the staff portal image (PORTAL_IMAGE)
	docker build -f services/staff_portal/Dockerfile -t $(PORTAL_IMAGE) .

scan: ## Trivy scan of SCAN_IMAGE (default API_IMAGE) -> reports/security/SCAN_REPORT; fails on CRITICAL vulnerabilities
	@mkdir -p reports/security $(TRIVY_CACHE_DIR) $(TRIVY_TMP_DIR)
	$(TRIVY) image --scanners vuln --severity CRITICAL,HIGH --ignore-unfixed --exit-code 0 $(SCAN_IMAGE)
	$(TRIVY) image --scanners vuln --skip-db-update --format json --output /reports/$(SCAN_REPORT) $(SCAN_IMAGE)
	$(TRIVY) image --scanners vuln --skip-db-update --severity CRITICAL --exit-code 1 $(SCAN_IMAGE)

scan-portal: ## Trivy scan of PORTAL_IMAGE -> reports/security/trivy-report-portal.json
	@$(MAKE) --no-print-directory scan SCAN_IMAGE=$(PORTAL_IMAGE) SCAN_REPORT=trivy-report-portal.json

# --- Responsible AI -----------------------------------------------------------
RETENTION_DAYS ?= 90

.PHONY: responsible-ai notebook-rai purge-logs

responsible-ai: $(PY) ## Fairness audit + mitigation, SHAP/LIME -> reports/{fairness,explainability}_report.*, figures, docs blocks
	MPLBACKEND=Agg $(PY) scripts/responsible_ai.py

notebook-rai: $(PY) ## Execute notebooks/02_fairness_explainability.ipynb in place
	$(PY) -c "import nbformat; from nbclient import NotebookClient; p='notebooks/02_fairness_explainability.ipynb'; \
	nb=nbformat.read(p, as_version=4); NotebookClient(nb, timeout=900, kernel_name='python3', \
	resources={'metadata': {'path': 'notebooks'}}).execute(); nbformat.write(nb, p)"

purge-logs: $(PY) ## Delete inference logs older than RETENTION_DAYS (default 90)
	$(PY) scripts/purge_inference_logs.py --retention-days $(RETENTION_DAYS)

# --- CI/CD --------------------------------------------------------------------
# GitHub Actions (.github/workflows/final-project-ci.yml) calls these same targets.
COV_MIN ?= 80
TEST_SUITES ?= unit integration data_quality model_validation
SMOKE_PROJECT ?= credit-risk-smoke
SMOKE_TIMEOUT ?= 300
ACTIONLINT_IMAGE ?= rhysd/actionlint:1.7.12
IMAGE_COMPOSE = API_IMAGE=$(API_IMAGE) PORTAL_IMAGE=$(PORTAL_IMAGE) docker compose -p $(SMOKE_PROJECT) \
	-f $(COMPOSE_FILE) -f deploy/compose/docker-compose.image.yml --env-file $(ENV_FILE)
SMOKE_API_KEY = $(shell sed -n 's/^API_KEYS=//p' $(ENV_FILE) | cut -d, -f1 | tr -d '[:space:]')
SMOKE_API_URL = http://localhost:$(or $(shell sed -n 's/^API_PORT=//p' $(ENV_FILE) | tr -d '[:space:]'),18020)
SMOKE_PORTAL_URL = http://localhost:$(or $(shell sed -n 's/^PORTAL_PORT=//p' $(ENV_FILE) | tr -d '[:space:]'),18030)

.PHONY: ci test-ci smoke actionlint

ci: lint test-ci docker-build docker-build-portal scan scan-portal smoke ## Whole CI pipeline locally, in the same order as GitHub Actions

test-ci: ## unit + integration + data_quality + model_validation, combined coverage gate >= COV_MIN
	@rm -f .coverage && mkdir -p reports/coverage
	@set -e; append=; for suite in $(TEST_SUITES); do \
	  echo "==> pytest tests/$$suite"; \
	  $(BIN)/pytest tests/$$suite --cov $$append --cov-report= --junitxml=reports/coverage/junit-$$suite.xml; \
	  append=--cov-append; \
	done
	$(BIN)/coverage report --skip-covered --fail-under=$(COV_MIN)
	$(BIN)/coverage xml -o reports/coverage/coverage.xml
	$(BIN)/coverage html -d reports/coverage/html

smoke: ## Compose smoke test of the prebuilt API_IMAGE + PORTAL_IMAGE: up -> health -> predict -> portal login/403/score -> down
	@{ $(IMAGE_COMPOSE) up -d --no-build api staff-portal \
	  && API_URL=$(SMOKE_API_URL) API_KEY=$(SMOKE_API_KEY) SMOKE_TIMEOUT=$(SMOKE_TIMEOUT) deploy/scripts/smoke_test.sh \
	  && ( set -a; . "$(abspath $(ENV_FILE))"; set +a; PORTAL_URL=$(SMOKE_PORTAL_URL) API_KEY=$(SMOKE_API_KEY) \
	       SMOKE_TIMEOUT=$(SMOKE_TIMEOUT) deploy/scripts/smoke_portal.sh ); } \
	  || { $(IMAGE_COMPOSE) ps -a; $(IMAGE_COMPOSE) logs --no-color --tail=200; $(IMAGE_COMPOSE) down -v; exit 1; }
	$(IMAGE_COMPOSE) down -v

actionlint: ## Lint the Final Project GitHub Actions workflows (actionlint + shellcheck)
	docker run --rm -v $(abspath $(CURDIR)/..):/repo -w /repo $(ACTIONLINT_IMAGE) -color \
	  .github/workflows/final-project-ci.yml .github/workflows/final-project-cd.yml

evidence: test-cov drift ## Machine-generated evidence: coverage/junit + drift report in reports/
	@echo "Evidence written to reports/ (coverage/, drift_report.html, drift_summary.json)"

clean: ## Remove caches and generated test artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage reports/coverage reports/security
	find . -name __pycache__ -type d -prune -not -path "./$(VENV)/*" -exec rm -rf {} +

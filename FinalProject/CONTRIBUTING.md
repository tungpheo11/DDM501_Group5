# 🤝 Contributing & Team Responsibilities Guide
## FinTech Real-Time Credit Default Risk Scoring Platform
> **Course:** DDM501 — AI in DevOps, DataOps, MLOps · FSB, FPT University  
> **Team:** Group 5 · Final Project Capstone

---

## 👥 1. Team Roles & Individual Responsibilities

To satisfy the rubric requirements for individual contributions and transparent engineering governance, responsibilities are allocated across the project lifecycle:

| Member / Role | Primary Responsibilities | Core Deliverables |
|---|---|---|
| **MLOps & DevOps Lead** | Multi-container Docker Compose orchestration, CI/CD pipeline design (GitHub Actions), Prometheus telemetry, and Grafana dashboard provisioning. | `docker-compose.yml`, `.github/workflows/`, `monitoring/`, infrastructure stability. |
| **Machine Learning Engineer** | Baseline model architecture (Random Forest, XGBoost), hyperparameter tuning, MLflow experiment tracking, Model Registry stage transitions. | `src/train.py`, `src/evaluate.py`, `scripts/retrain.py`, MLflow integration. |
| **DataOps & Pipeline Engineer** | Data ingestion, schema validation gates, feature engineering, and Apache Airflow closed-loop retraining DAG design. | `src/data_loader.py`, `src/preprocessing.py`, `airflow/dags/`, data pipelines. |
| **Quality, Security & AI Ethics** | Test suite implementation (>80% coverage), Data Drift detection with Evidently AI, Responsible AI fairness & bias audits, SHAP explainability. | `tests/`, `src/fairness.py`, `src/explainability.py`, `scripts/detect_drift.py`. |

---

## 🌿 2. Git Branching Strategy

We follow a structured GitFlow / Feature Branching methodology:

```
main (Production-ready releases only)
  ▲
  │ Pull Request (Requires CI pass & 1 peer review)
  │
feature/final-project (Integration branch)
  ▲
  ├── feature/ml-pipeline-fairness
  ├── feature/cicd-smoke-tests
  └── feature/airflow-orchestration
```

### Branch Naming Conventions:
- `feature/<feature-name>`: New capabilities (e.g., `feature/fairness-audit`).
- `fix/<bug-name>`: Bug fixes (e.g., `fix/api-pydantic-validation`).
- `docs/<doc-name>`: Documentation updates (e.g., `docs/architecture-c4`).
- `test/<test-name>`: Test suite expansions (e.g., `test/data-quality-gates`).

---

## 📝 3. Commit Message Standards

Commits must follow the **Conventional Commits** specification:

```
<type>(<scope>): <short description in present tense>

[optional body explaining rationale and trade-offs]
```

### Valid Types:
- `feat`: A new feature or endpoint.
- `fix`: A bug fix or patch.
- `docs`: Documentation changes (`README.md`, `ARCHITECTURE.md`).
- `test`: Adding or updating tests.
- `refactor`: Code changes that neither fix a bug nor add a feature.
- `ci`: Changes to CI/CD workflows and automation scripts.
- `perf`: Performance improvements.

---

## 💻 4. Local Development Workflow

### Step 1: Clone and Environment Setup
```bash
# Clone the repository
git clone git@github.com:tungpheo11/DDM501_Group5.git
cd DDM501_Group5/FinalProject

# Option A: Using Astral uv (Recommended for speed)
uv sync --dev
source .venv/bin/activate

# Option B: Standard Python venv & pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Code Quality & Linting
Before submitting code, ensure all files conform to PEP 8 standards:
```bash
# Run Flake8 linter
uv run flake8 src app tests scripts

# Run code formatter
uv run black --check src app tests
```

### Step 3: Run Full Test Suite
Every commit must maintain **>80% test coverage**:
```bash
# Run pytest with coverage report
uv run pytest --cov=src --cov=app --cov-report=term-missing
```

---

## 🔍 5. Pull Request & Review Checklist

Before opening a Pull Request into `feature/final-project` or `main`:
1. [ ] All unit, integration, data quality, and model validation tests pass (`pytest`).
2. [ ] Test coverage is strictly **$\ge 80\%$**.
3. [ ] `flake8` returns 0 syntax or style violations.
4. [ ] Multi-container stack boots cleanly via `docker compose up -d`.
5. [ ] End-to-end smoke test script `./scripts/test_e2e.sh` passes all 5 validation gates.

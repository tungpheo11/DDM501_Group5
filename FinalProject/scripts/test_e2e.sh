#!/usr/bin/env bash
# ==============================================================================
# Comprehensive End-to-End Validation Script for Credit Default Risk MLOps Platform
# Validates Code Quality, Test Coverage (>80%), Schema Gates, Responsible AI,
# and Model Serving SLAs.
# ==============================================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "\n${BOLD}${BLUE}======================================================================"
echo -e "   CREDIT RISK MLOPS PLATFORM — END-TO-END VALIDATION GATES           "
echo -e "======================================================================${NC}\n"

# 1. Code Style & Flake8 Linting
echo -e "${BOLD}[1/5] Gate 1: Code Quality & Flake8 Linting...${NC}"
if uv run flake8 src app tests scripts simulations; then
    echo -e "${GREEN}✓ Code style and syntax clean (0 violations)${NC}\n"
else
    echo -e "${RED}✗ Gate 1 Failed: Flake8 violations detected!${NC}"
    exit 1
fi

# 2. Automated Test Suite & Coverage Gate (>80%)
echo -e "${BOLD}[2/5] Gate 2: Full Test Suite & Coverage Enforcement (>80%)...${NC}"
if uv run pytest -v --cov=src --cov=app --cov-report=term-missing --cov-fail-under=80; then
    echo -e "${GREEN}✓ All unit and integration tests passed with >=80% coverage${NC}\n"
else
    echo -e "${RED}✗ Gate 2 Failed: Test suite failed or coverage below 80%!${NC}"
    exit 1
fi

# 3. Data Quality & Schema Gate
echo -e "${BOLD}[3/5] Gate 3: Data Quality & Domain Boundary Integrity...${NC}"
if uv run pytest tests/test_data_quality.py -v; then
    echo -e "${GREEN}✓ All 23 feature boundaries, non-emptiness, and zero nulls verified${NC}\n"
else
    echo -e "${RED}✗ Gate 3 Failed: Data quality violations detected!${NC}"
    exit 1
fi

# 4. Responsible AI & Fairness Audit
echo -e "${BOLD}[4/5] Gate 4: Responsible AI Fairness, Bias & Explainability Audit...${NC}"
if uv run python scripts/run_fairness_audit.py; then
    echo -e "${GREEN}✓ Responsible AI audit passed (Four-Fifths Rule & Explainability verified)${NC}\n"
else
    echo -e "${RED}✗ Gate 4 Failed: Algorithmic bias detected or audit failure!${NC}"
    exit 1
fi

# 5. Model Validation & Latency SLA (< 50ms)
echo -e "${BOLD}[5/5] Gate 5: Model Performance & Latency SLA Validation...${NC}"
if uv run pytest tests/test_model_validation.py -v; then
    echo -e "${GREEN}✓ Model quality gate (ROC-AUC >= 0.70) and SLA (< 50ms) verified${NC}\n"
else
    echo -e "${RED}✗ Gate 5 Failed: Performance gate or latency SLA not met!${NC}"
    exit 1
fi

echo -e "\n${BOLD}${GREEN}======================================================================"
echo -e "   ALL 5 MLOPS PIPELINE VALIDATION GATES PASSED SUCCESSFULLY!         "
echo -e "======================================================================${NC}\n"

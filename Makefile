d# FaceGate — developer commands. Run `make help`.
PY      ?= .venv/bin/python
UV      ?= uv
HOST    ?= 0.0.0.0
PORT    ?= 8100
DATA    ?= data/eval_faces
ADAFACE_CKPT ?= models/adaface_ir101_webface12m.ckpt
ADAFACE_ARCH ?= ir_101

.DEFAULT_GOAL := help
.PHONY: help install install-export models adaface serve dev test lint format status evaluate enroll-dir clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

install: ## Create .venv (Python 3.12) and install runtime + dev deps
	$(UV) venv --python 3.12 .venv
	$(UV) pip install --python $(PY) -e ".[dev]"

install-export: ## Add torch (CPU) + onnx, needed only to convert AdaFace .ckpt → ONNX
	$(UV) pip install --python $(PY) -e ".[dev,export]"

models: ## Download SCRFD (det_10g) + ArcFace (w600k_r50) into models/
	$(PY) scripts/download_models.py --out models

adaface: ## Convert ADAFACE_CKPT to models/adaface_ir101_webface12m.onnx (needs install-export)
	$(PY) scripts/export_adaface_onnx.py --ckpt $(ADAFACE_CKPT) --arch $(ADAFACE_ARCH) --out models/adaface_ir101_webface12m.onnx

serve: ## Run API + console at http://localhost:$(PORT)
	$(PY) -m uvicorn facegate.api.main:app --host $(HOST) --port $(PORT)

dev: ## Run with auto-reload
	$(PY) -m uvicorn facegate.api.main:app --host $(HOST) --port $(PORT) --reload --reload-dir src

status: ## Print model + gallery status
	$(PY) -m facegate.cli status

enroll-dir: ## Bulk-enroll DATA=<root>/<Name>[__EMPID]/*.jpg
	$(PY) -m facegate.cli enroll-dir $(DATA)

evaluate: ## Calibrate thresholds on DATA=<root>/<person>/*.jpg → reports/evaluation.json
	$(PY) -m facegate.cli evaluate $(DATA) --out reports/evaluation.json

test: ## Run the test-suite
	$(PY) -m pytest

lint: ## Static checks
	$(PY) -m ruff check src tests scripts

format: ## Auto-format
	$(PY) -m ruff format src tests scripts && $(PY) -m ruff check --fix src tests scripts

clean: ## Remove caches (keeps models/ and data/)
	rm -rf .pytest_cache .ruff_cache reports
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

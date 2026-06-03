# Conclave build / dev / Ollama-prereq targets.
#
# Created in Phase 3.5.0 C2.5 (see discoveries/KB-AND-GRAPH-BUILD-PLAN.md).
# Targets a solo-founder local-dev workflow; CI hooks are out of scope here.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:

# --- Model selection -------------------------------------------------------
#
# Q1 bake-off (C3) + extraction (C13) + importance (C14) + ER tiebreak (C15) +
# Mem0 upsert (C16) all want a local LLM. Project default is the existing
# qwen2.5-conclave (built from qwen2.5:7b-instruct with num_ctx=8192 — see
# ollama/Modelfile.qwen-conclave). The KB-AND-GRAPH-ROADMAP-v2 §3.5a.4
# nominally calls for qwen2.5:14b; we deviate to the existing in-tree model
# because (a) the bake-off is a *relative* prompt-shape comparison and
# robust to model choice, (b) avoids a ~9GB unsolicited pull, (c) keeps
# production single-model. If C13 extraction F1 disappoints, escape hatch
# is `make ollama-prereqs-14b` + an EVAL.md decision record.

OLLAMA_LLM_MODEL ?= qwen2.5-conclave:latest
OLLAMA_EMBED_MODEL ?= nomic-embed-text:v1.5
OLLAMA_HOST ?= http://127.0.0.1:11434

.PHONY: help ollama-check ollama-prereqs ollama-prereqs-14b ollama-models

help:
	@echo "Targets:"
	@echo "  ollama-check         — verify Ollama is up and required models are pulled"
	@echo "  ollama-prereqs       — pull project-default models ($(OLLAMA_LLM_MODEL) + $(OLLAMA_EMBED_MODEL))"
	@echo "  ollama-prereqs-14b   — escape hatch: pull qwen2.5:14b for roadmap-literal mode"
	@echo "  ollama-models        — list currently pulled models"

ollama-check:
	@printf "Ollama daemon @ $(OLLAMA_HOST): "
	@if curl -sf --max-time 2 "$(OLLAMA_HOST)/api/version" >/dev/null; then \
		echo "up ✓"; \
	else \
		echo "DOWN ✗ — start with: brew services start ollama (or `ollama serve`)"; \
		exit 1; \
	fi
	@printf "LLM model ($(OLLAMA_LLM_MODEL)): "
	@if ollama list | awk '{print $$1}' | grep -qx "$(OLLAMA_LLM_MODEL)"; then \
		echo "present ✓"; \
	else \
		echo "MISSING ✗ — run: make ollama-prereqs"; \
		exit 1; \
	fi
	@printf "Embed model ($(OLLAMA_EMBED_MODEL)): "
	@if ollama list | awk '{print $$1}' | grep -qx "$(OLLAMA_EMBED_MODEL)"; then \
		echo "present ✓"; \
	else \
		echo "MISSING ✗ — run: make ollama-prereqs"; \
		exit 1; \
	fi

ollama-prereqs:
	@echo "Pulling LLM: $(OLLAMA_LLM_MODEL)"
	@if [ "$(OLLAMA_LLM_MODEL)" = "qwen2.5-conclave:latest" ]; then \
		if ollama list | awk '{print $$1}' | grep -qx "qwen2.5-conclave:latest"; then \
			echo "  already present"; \
		else \
			echo "  building from ollama/Modelfile.qwen-conclave"; \
			ollama pull qwen2.5:7b-instruct; \
			ollama create qwen2.5-conclave -f ollama/Modelfile.qwen-conclave; \
		fi; \
	else \
		ollama pull "$(OLLAMA_LLM_MODEL)"; \
	fi
	@echo "Pulling embed model: $(OLLAMA_EMBED_MODEL)"
	@ollama pull "$(OLLAMA_EMBED_MODEL)"
	@echo ""
	@echo "Done. Verify with: make ollama-check"

ollama-prereqs-14b:
	@echo "Pulling qwen2.5:14b (roadmap-literal mode; ~9GB)..."
	@ollama pull qwen2.5:14b
	@echo "Done. To use it for the 3.5 pipeline, run with:"
	@echo "  OLLAMA_LLM_MODEL=qwen2.5:14b make ollama-check"

ollama-models:
	@ollama list

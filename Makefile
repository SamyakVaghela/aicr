SHELL := /bin/bash
ROOT  := $(CURDIR)
export PYTHONPATH := $(ROOT)/src

# Loads .env (GEMINI_API_KEY etc.) into every recipe below, if it exists.
ifneq (,$(wildcard .env))
include .env
export
endif

PROVIDER ?= gemini

.PHONY: help install samples-repo smoke smoke-v good-01 bad-01 doctor clean

help:
	@echo "make install      - pip install -e '.[dev]'"
	@echo "make samples-repo - turn samples/ into a scratch git repo (idempotent)"
	@echo "make smoke        - run the full smoke suite (pass/fail table)"
	@echo "make smoke-v      - same, verbose (every finding)"
	@echo "make good-01      - review samples/good_01_payments.py (expect PASS)"
	@echo "make bad-01       - review samples/bad_01_payments.py (expect BLOCK)"
	@echo "make doctor       - check config, hook, provider connectivity"
	@echo "make clean        - remove the scratch git repo in samples/"
	@echo ""
	@echo "Override provider with PROVIDER=..., e.g.: make bad-01 PROVIDER=anthropic"

install:
	pip install -e '.[dev]'

samples-repo:
	@if [ ! -d samples/.git ]; then \
		cd samples && git init -q --initial-branch=main . && git add -A && git commit -qm "smoke samples" ; \
		echo "samples/ is now a scratch git repo" ; \
	else \
		echo "samples/ is already a scratch git repo" ; \
	fi

smoke:
	python3 samples/run-smoke.py --provider $(PROVIDER)

smoke-v:
	python3 samples/run-smoke.py --provider $(PROVIDER) -v

good-01: samples-repo
	@python3 -m aicr review --repo samples --files good_01_payments.py --provider $(PROVIDER); \
	code=$$?; \
	if [ $$code -eq 0 ]; then echo "--- as expected: PASS (exit 0) ---"; \
	else echo "--- unexpected: exit $$code, expected 0/PASS ---"; fi

bad-01: samples-repo
	@python3 -m aicr review --repo samples --files bad_01_payments.py --provider $(PROVIDER); \
	code=$$?; \
	if [ $$code -eq 1 ]; then echo "--- as expected: BLOCKED (exit 1) ---"; \
	else echo "--- unexpected: exit $$code, expected 1/BLOCK ---"; fi

doctor:
	python3 -m aicr doctor --repo samples --provider $(PROVIDER)

clean:
	rm -rf samples/.git

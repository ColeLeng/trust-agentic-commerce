PYTHON ?= python3
WANDB_PROJECT ?= cjzhong/test
CODEX_SESSION_ID ?= 019e7fc0-3319-7802-b166-cc0d8a418079
CODEX_WATCH_INTERVAL_SECONDS ?= 5
PID_FILE ?= .codex-session-watcher.pid
LOG_FILE ?= codex-session-watcher.log

ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: install trace-session trace-new watch-session watch-session-bg stop-watch-session json-qa-eval check

install:
	$(PYTHON) -m pip install -r requirements.txt

trace-session:
	WANDB_PROJECT="$(WANDB_PROJECT)" CODEX_SESSION_ID="$(CODEX_SESSION_ID)" $(PYTHON) trace_example.py

trace-new:
	WANDB_PROJECT="$(WANDB_PROJECT)" $(PYTHON) trace_example.py

watch-session:
	PYTHONUNBUFFERED=1 WANDB_PROJECT="$(WANDB_PROJECT)" CODEX_SESSION_ID="$(CODEX_SESSION_ID)" CODEX_WATCH_INTERVAL_SECONDS="$(CODEX_WATCH_INTERVAL_SECONDS)" WATCH_CODEX_SESSION=1 $(PYTHON) trace_example.py

watch-session-bg:
	PYTHONUNBUFFERED=1 WANDB_PROJECT="$(WANDB_PROJECT)" CODEX_SESSION_ID="$(CODEX_SESSION_ID)" CODEX_WATCH_INTERVAL_SECONDS="$(CODEX_WATCH_INTERVAL_SECONDS)" WATCH_CODEX_SESSION=1 nohup $(PYTHON) trace_example.py > "$(LOG_FILE)" 2>&1 & echo $$! > "$(PID_FILE)"
	@echo "watcher pid: $$(cat "$(PID_FILE)")"
	@echo "watcher log: $(LOG_FILE)"

stop-watch-session:
	@if [ -f "$(PID_FILE)" ]; then kill "$$(cat "$(PID_FILE)")" 2>/dev/null || true; rm "$(PID_FILE)"; else echo "no watcher pid file found"; fi

json-qa-eval:
	WANDB_PROJECT="$(WANDB_PROJECT)" RUN_JSON_QA_EVAL=1 $(PYTHON) trace_example.py

check:
	$(PYTHON) -m py_compile trace_example.py

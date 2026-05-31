# W&B Weave Trace Example

This is a minimal W&B Weave trace use case that records real Codex agent usage.
The script runs `codex exec --json`, parses the event stream, and records the
Codex session/thread ID, final answer, token usage, duration, exit status, and
raw events in Weave.

## Setup

```bash
pip install -r requirements.txt
```

Set `WANDB_API_KEY` when you want to upload traces to Weave. Without it, the
script still prints the parsed Codex usage locally.

Optional overrides:

```bash
export WANDB_PROJECT="cjzhong/test"
export CODEX_MODEL="gpt-5"
export CODEX_WORKDIR="/path/to/workspace"
export CODEX_PROMPT="Inspect this directory and summarize it."
```

## Run

```bash
python trace_example.py
```

The same workflows are available through `make`:

```bash
make install
make trace-session
make trace-new
make watch-session
make watch-session-bg
make stop-watch-session
make json-qa-eval
make check
```

To inspect and trace a specific local Codex session without adding a new turn:

```bash
CODEX_SESSION_ID="019e7fc0-3319-7802-b166-cc0d8a418079" python trace_example.py
```

To filter out one or more sessions from the recorded payload:

```bash
export CODEX_EXCLUDED_SESSION_IDS="session-id-1,session-id-2"
python trace_example.py
```

Filtered sessions return a small redacted trace result with `filtered: true`.
The trace will appear under the configured W&B project.

## Session Watcher

Run a foreground process that keeps polling a Codex session log and publishes
new messages, usage snapshots, and tool events to Weave:

```bash
make watch-session
```

Start the same watcher in the background:

```bash
make watch-session-bg
```

Stop it with:

```bash
make stop-watch-session
```

Useful overrides:

```bash
make watch-session-bg CODEX_SESSION_ID="019e7fc0-3319-7802-b166-cc0d8a418079"
make watch-session-bg CODEX_WATCH_INTERVAL_SECONDS=2
CODEX_WATCH_FROM_START=1 make watch-session
```

By default, the watcher starts from the current end of the session file and
publishes only newly appended events. Set `CODEX_WATCH_FROM_START=1` to backfill
the existing session into Weave.

## JSON QA Evaluation

Run the W&B JSON QA evaluation with:

```bash
make json-qa-eval
```

This calls `run_json_qa_eval()` in `trace_example.py`, loads
`weave:///wandb/json-qa/object/json-qa:v3`, evaluates `JsonModel`, and scores
whether the model returns the expected XML answer format.

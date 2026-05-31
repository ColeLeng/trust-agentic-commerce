import os
import json
import asyncio
import re
import subprocess
import time
from pathlib import Path
from textwrap import dedent
from typing import Any, Optional

import weave
from openai import OpenAI


WANDB_PROJECT = os.getenv("WANDB_PROJECT", "cjzhong/test")
MODEL = os.getenv("WANDB_MODEL", "OpenPipe/Qwen3-14B-Instruct")
JSON_QA_DATASET_URI = os.getenv(
    "JSON_QA_DATASET_URI",
    "weave:///wandb/json-qa/object/json-qa:v3",
)
CODEX_MODEL = os.getenv("CODEX_MODEL")
CODEX_WORKDIR = os.getenv("CODEX_WORKDIR", os.getcwd())
CODEX_HOME = Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))
CODEX_WATCH_INTERVAL_SECONDS = float(os.getenv("CODEX_WATCH_INTERVAL_SECONDS", "5"))
CODEX_WATCH_FROM_START = os.getenv("CODEX_WATCH_FROM_START") == "1"
WEAVE_ACTIVE = False
CODEX_EXCLUDED_SESSION_IDS = {
    value.strip()
    for value in os.getenv(
        "CODEX_EXCLUDED_SESSION_IDS",
        os.getenv("CODEX_EXCLUDED_THREAD_IDS", ""),
    ).split(",")
    if value.strip()
}


def get_wandb_api_key() -> str:
    api_key = os.getenv("WANDB_API_KEY")
    if not api_key:
        raise RuntimeError(
            "WANDB_API_KEY is not set. Export it before running this example."
        )
    return api_key


def init_weave() -> bool:
    global WEAVE_ACTIVE
    if WEAVE_ACTIVE:
        return True
    if not os.getenv("WANDB_API_KEY"):
        print("[trace] WANDB_API_KEY is not set; running without Weave upload.")
        return False
    try:
        weave.init(WANDB_PROJECT)
    except Exception as exc:
        print(f"[trace] weave.init failed ({exc}); running without Weave upload.")
        return False
    WEAVE_ACTIVE = True
    return True


class JsonModel(weave.Model):
    prompt: weave.Prompt = weave.StringPrompt(
        dedent(
            """
            You are an assistant that answers questions about JSON data provided by
            the user. The JSON data represents structured information of various
            kinds, and may be deeply nested. In the first user message, you will
            receive the JSON data under a label called 'context', and a question
            under a label called 'question'. Your job is to answer the question
            with as much accuracy and brevity as possible. Give only the answer
            with no preamble. You must output the answer in XML format, between
            <answer> and </answer> tags.
            """
        )
    )
    model: str = MODEL
    _client: OpenAI

    def __init__(self):
        super().__init__()
        self._client = OpenAI(
            base_url="https://api.inference.wandb.ai/v1",
            api_key=get_wandb_api_key(),
            project=WANDB_PROJECT,
        )

    @weave.op
    def predict(self, context: str, question: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.prompt.format()},
                {
                    "role": "user",
                    "content": f"Context: {context}\nQuestion: {question}",
                },
            ],
        )
        return response.choices[0].message.content


@weave.op
def correct_answer_format(answer: str, output: str) -> dict[str, bool]:
    parsed_output = re.search(r"<answer>(.*?)</answer>", output, re.DOTALL)
    if parsed_output is None:
        return {"correct_answer": False, "correct_format": False}
    return {
        "correct_answer": parsed_output.group(1) == answer,
        "correct_format": True,
    }


async def run_json_qa_eval(
    dataset_uri: str = JSON_QA_DATASET_URI,
    eval_name: str = "json-qa-eval",
) -> Any:
    get_wandb_api_key()
    if not init_weave():
        raise RuntimeError("Weave is not active. Set WANDB_API_KEY before running evals.")

    jsonqa = weave.Dataset.from_uri(dataset_uri).to_pandas()
    evaluation = weave.Evaluation(
        name=eval_name,
        dataset=weave.Dataset.from_pandas(jsonqa),
        scorers=[correct_answer_format],
    )
    return await evaluation.evaluate(JsonModel())


def is_excluded_codex_session(session_id: Optional[str]) -> bool:
    return bool(session_id and session_id in CODEX_EXCLUDED_SESSION_IDS)


def find_codex_session_file(session_id: str) -> Path:
    sessions_dir = CODEX_HOME / "sessions"
    matches = sorted(sessions_dir.rglob(f"*{session_id}*.jsonl"))
    if not matches:
        raise FileNotFoundError(f"No Codex session log found for {session_id}")
    return matches[-1]


def parse_codex_session_log(path: Path) -> dict[str, Any]:
    metadata = None
    messages = []
    usage_snapshots = []
    tool_events = []

    with path.open("r", encoding="utf-8") as session_file:
        for line in session_file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "session_meta":
                payload = event.get("payload", {})
                metadata = {
                    "id": payload.get("id"),
                    "timestamp": payload.get("timestamp"),
                    "cwd": payload.get("cwd"),
                    "cli_version": payload.get("cli_version"),
                    "source": payload.get("source"),
                    "model_provider": payload.get("model_provider"),
                    "git": payload.get("git"),
                }
                continue

            if event.get("type") != "event_msg":
                continue

            payload = event.get("payload", {})
            payload_type = payload.get("type")
            if payload_type in {"user_message", "agent_message"}:
                messages.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "role": "user"
                        if payload_type == "user_message"
                        else "assistant",
                        "message": payload.get("message"),
                    }
                )
            elif payload_type == "token_count":
                usage_snapshots.append(payload.get("info", {}))
            elif payload_type in {"exec_command_begin", "exec_command_end"}:
                tool_events.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "type": payload_type,
                        "call_id": payload.get("call_id"),
                        "cmd": payload.get("cmd"),
                        "success": payload.get("success"),
                    }
                )

    latest_usage = usage_snapshots[-1] if usage_snapshots else None
    return {
        "metadata": metadata,
        "message_count": len(messages),
        "messages": messages,
        "tool_event_count": len(tool_events),
        "tool_events": tool_events,
        "usage": latest_usage,
        "usage_snapshots": usage_snapshots,
    }


def codex_session_update_from_event(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    event_type = event.get("type")
    if event_type == "session_meta":
        payload = event.get("payload", {})
        return {
            "timestamp": event.get("timestamp"),
            "kind": "session_meta",
            "metadata": {
                "id": payload.get("id"),
                "timestamp": payload.get("timestamp"),
                "cwd": payload.get("cwd"),
                "cli_version": payload.get("cli_version"),
                "source": payload.get("source"),
                "model_provider": payload.get("model_provider"),
                "git": payload.get("git"),
            },
        }

    if event_type != "event_msg":
        return None

    payload = event.get("payload", {})
    payload_type = payload.get("type")
    if payload_type in {"user_message", "agent_message"}:
        return {
            "timestamp": event.get("timestamp"),
            "kind": "message",
            "role": "user" if payload_type == "user_message" else "assistant",
            "message": payload.get("message"),
        }
    if payload_type == "token_count":
        return {
            "timestamp": event.get("timestamp"),
            "kind": "usage",
            "usage": payload.get("info", {}),
            "rate_limits": payload.get("rate_limits"),
        }
    if payload_type in {"exec_command_begin", "exec_command_end"}:
        return {
            "timestamp": event.get("timestamp"),
            "kind": "tool_event",
            "type": payload_type,
            "call_id": payload.get("call_id"),
            "cmd": payload.get("cmd"),
            "success": payload.get("success"),
        }
    return None


def read_codex_session_updates(path: Path, offset: int) -> tuple[list[dict[str, Any]], int]:
    updates = []
    with path.open("r", encoding="utf-8") as session_file:
        session_file.seek(offset)
        while True:
            line_start = session_file.tell()
            line = session_file.readline()
            if not line:
                return updates, session_file.tell()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return updates, line_start

            update = codex_session_update_from_event(event)
            if update is not None:
                updates.append(update)


@weave.op
def publish_codex_session_updates(
    session_id: str,
    session_file: str,
    start_offset: int,
    end_offset: int,
    updates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent": "codex",
        "session_id": session_id,
        "session_file": session_file,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "update_count": len(updates),
        "updates": updates,
    }


def watch_codex_session(
    session_id: str,
    interval_seconds: float = CODEX_WATCH_INTERVAL_SECONDS,
    from_start: bool = CODEX_WATCH_FROM_START,
) -> None:
    get_wandb_api_key()
    if is_excluded_codex_session(session_id):
        raise RuntimeError(f"Refusing to watch excluded Codex session {session_id}")
    if not init_weave():
        raise RuntimeError("Weave is not active. Set WANDB_API_KEY before watching.")

    session_file = find_codex_session_file(session_id)
    offset = 0 if from_start else session_file.stat().st_size
    print(
        "[trace] watching "
        f"{session_id} at {session_file} from offset {offset}; "
        f"poll interval {interval_seconds}s",
        flush=True,
    )

    while True:
        start_offset = offset
        updates, offset = read_codex_session_updates(session_file, offset)
        if updates:
            publish_codex_session_updates(
                session_id=session_id,
                session_file=str(session_file),
                start_offset=start_offset,
                end_offset=offset,
                updates=updates,
            )
            print(
                "[trace] published "
                f"{len(updates)} update(s) for {session_id}; offset {offset}",
                flush=True,
            )
        time.sleep(interval_seconds)


@weave.op
def inspect_codex_session(session_id: str) -> dict[str, Any]:
    if is_excluded_codex_session(session_id):
        return {
            "agent": "codex",
            "session_id": session_id,
            "filtered": True,
            "reason": "session_id is listed in CODEX_EXCLUDED_SESSION_IDS",
        }

    session_file = find_codex_session_file(session_id)
    parsed = parse_codex_session_log(session_file)
    return {
        "agent": "codex",
        "session_id": session_id,
        "session_file": str(session_file),
        "filtered": False,
        **parsed,
    }


def parse_codex_events(output: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    final_message = None
    thread_id = None
    usage = None

    for line in output.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        events.append(event)
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        elif event_type == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                final_message = item.get("text")
        elif event_type == "turn.completed":
            usage = event.get("usage")

    return {
        "thread_id": thread_id,
        "final_message": final_message,
        "usage": usage,
        "events": events,
    }


def codex_command(prompt: str, session_id: Optional[str] = None) -> list[str]:
    command = ["codex", "exec"]
    if session_id:
        command.append("resume")
    command.extend(["--json", "--ephemeral", "--skip-git-repo-check"])
    if CODEX_MODEL:
        command.extend(["--model", CODEX_MODEL])
    if session_id:
        command.append(session_id)
    else:
        command.extend(["--sandbox", "read-only"])
    command.append(prompt)
    return command


def _run_codex_agent(prompt: str, session_id: Optional[str] = None) -> dict[str, Any]:
    started_at = time.time()
    completed = subprocess.run(
        codex_command(prompt, session_id),
        cwd=CODEX_WORKDIR,
        input="",
        text=True,
        capture_output=True,
        check=False,
    )
    duration_ms = round((time.time() - started_at) * 1000, 2)
    parsed = parse_codex_events(completed.stdout)
    filtered = is_excluded_codex_session(session_id) or is_excluded_codex_session(
        parsed["thread_id"]
    )

    return {
        "agent": "codex",
        "prompt": prompt,
        "requested_session_id": session_id,
        "thread_id": parsed["thread_id"],
        "filtered": filtered,
        "exit_code": completed.returncode,
        "duration_ms": duration_ms,
        "usage": parsed["usage"],
        "final_message": None if filtered else parsed["final_message"],
        "stdout": None if filtered else completed.stdout,
        "stderr": completed.stderr,
        "events": [] if filtered else parsed["events"],
    }


@weave.op
def run_codex_agent(prompt: str, session_id: Optional[str] = None) -> dict[str, Any]:
    if is_excluded_codex_session(session_id):
        return {
            "agent": "codex",
            "requested_session_id": session_id,
            "filtered": True,
            "reason": "session_id is listed in CODEX_EXCLUDED_SESSION_IDS",
        }
    return _run_codex_agent(prompt, session_id)


@weave.op
def route_support_ticket(ticket: str) -> str:
    client = OpenAI(
        base_url="https://api.inference.wandb.ai/v1",
        api_key=get_wandb_api_key(),
        project=WANDB_PROJECT,
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You route customer support tickets. Return a compact JSON-like "
                    "summary with fields: category, priority, owner, and next_action."
                ),
            },
            {"role": "user", "content": ticket},
        ],
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    if os.getenv("RUN_JSON_QA_EVAL") == "1":
        asyncio.run(run_json_qa_eval())
        raise SystemExit(0)

    codex_session_id = os.getenv("CODEX_SESSION_ID")
    if os.getenv("WATCH_CODEX_SESSION") == "1":
        if not codex_session_id:
            raise RuntimeError("CODEX_SESSION_ID is required when WATCH_CODEX_SESSION=1")
        watch_codex_session(codex_session_id)
        raise SystemExit(0)

    prompt = os.getenv(
        "CODEX_PROMPT",
        (
            "Inspect this directory and summarize what the trace example does. "
            "Return a concise answer."
        ),
    )
    init_weave()

    if codex_session_id:
        result = inspect_codex_session(codex_session_id)
    else:
        result = run_codex_agent(prompt)
    print(json.dumps(result, indent=2))

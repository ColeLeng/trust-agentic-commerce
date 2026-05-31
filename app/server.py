"""
app/server.py -- the VISUAL DEMO server (zero extra dependencies).

OWNER: Glue

A tiny stdlib http.server that powers the demo UI in app/web/. It does two things:

  GET  /                      -> serves the single-page visualization (app/web)
  GET  /api/run?strategy=...  -> LIVE-TRIGGERS the full agent pipeline for one
                                 contamination strategy and returns the complete
                                 data-flow trace (what every agent consumed +
                                 produced) as JSON.

The browser hits /api/run, which runs the same `build_audit` code path as run.py
(mock-first: works on a fresh clone with no codex CLI), then reconstructs a trace
via app/trace.build_trace. Results are cached per strategy so re-rendering /
re-sliding the contamination level is instant.

    python -m app.server            # then open http://localhost:8000
    python -m app.server --port 8001

No Flask/FastAPI: uses only the standard library so the demo never goes dark.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load this repo's .env so WANDB_API_KEY (Weave tracing) + WEAVE_* are available.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

# DEMO DEFAULT = MOCK MODE. The contamination slider re-renders instantly and the
# money-shot is deterministic. Real agents (each isolated scout = one Claude call)
# are slow per sweep, so they're opt-in: launch with DEMO_REAL=1 to use them. The
# scout/baseline gate on ANTHROPIC_API_KEY, so we drop it from the environment for
# the demo unless real mode is explicitly requested.
_REAL = os.getenv("DEMO_REAL", "").lower() in ("1", "true", "yes")
if not _REAL:
    os.environ.pop("ANTHROPIC_API_KEY", None)

from app.demo_engine import DEFAULT_SCENARIO, build_trace  # noqa: E402
from tracing import init_tracing  # noqa: E402

# Activate Weave once at import. Every @traced agent call (planner, each isolated
# scout, concierge, baseline) is then logged to the Weave project so you can watch
# every agent action when the system runs.
_WEAVE_ACTIVE = init_tracing()
_WEAVE_PROJECT = os.getenv("WEAVE_PROJECT", "trust-agentic-commerce")
_WEAVE_ENTITY = os.getenv("WEAVE_ENTITY", "")
_WEAVE_URL = (
    f"https://wandb.ai/{_WEAVE_ENTITY}/{_WEAVE_PROJECT}/weave"
    if _WEAVE_ACTIVE and _WEAVE_ENTITY
    else ("https://wandb.ai/home" if _WEAVE_ACTIVE else "")
)

WEB_DIR = Path(__file__).resolve().parent / "web"

_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def get_trace(fresh: bool = False, n_stores: int | None = None) -> dict:
    """Run (or fetch cached) the full buyer-journey audit and return its trace.

    fresh=True re-executes the whole pipeline (planner -> per-seller scout -> the
    four sub-agents for every store), which logs a NEW Weave trace — so the Re-run
    button produces a fresh set of agent actions you can watch in Weave.
    """
    key = f"n{n_stores or DEFAULT_SCENARIO['nStores']}"
    with _CACHE_LOCK:
        if not fresh and key in _CACHE:
            return _CACHE[key]
    scenario = None
    if n_stores:
        scenario = {"nStores": max(2, min(12, int(n_stores)))}
    trace = build_trace(scenario, used_real=_REAL)
    trace["weaveActive"] = _WEAVE_ACTIVE
    trace["weaveUrl"] = _WEAVE_URL
    with _CACHE_LOCK:
        _CACHE[key] = trace
    return trace


class Handler(BaseHTTPRequestHandler):
    server_version = "TrustCommerceDemo/1.0"

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        sys.stderr.write("[server] " + (fmt % args) + "\n")

    # ----- helpers ---------------------------------------------------------- #
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(404, "Not found")
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ----- routing ---------------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path

        if route == "/api/run":
            qs = parse_qs(parsed.query)
            fresh = (qs.get("fresh") or ["0"])[0] in ("1", "true", "yes")
            n_raw = (qs.get("stores") or [None])[0]
            n_stores = int(n_raw) if (n_raw and n_raw.isdigit()) else None
            try:
                self._send_json(get_trace(fresh=fresh, n_stores=n_stores))
            except Exception as exc:  # never let the demo crash the page
                import traceback
                traceback.print_exc()
                self._send_json({"error": str(exc)}, status=500)
            return

        if route == "/api/tracing":
            self._send_json({
                "weaveActive": _WEAVE_ACTIVE,
                "weaveUrl": _WEAVE_URL,
                "project": _WEAVE_PROJECT,
                "entity": _WEAVE_ENTITY,
            })
            return

        if route == "/api/checks":
            from app.demo_engine import CHECKS
            self._send_json({"checks": CHECKS})
            return

        if route in ("/", "/index.html"):
            self._send_file(WEB_DIR / "index.html")
            return

        # static assets, sandboxed to WEB_DIR
        rel = route.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() in target.parents or target == WEB_DIR.resolve():
            self._send_file(target)
        else:
            self.send_error(403, "Forbidden")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trust Agentic Commerce visual demo server.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--warm", action="store_true",
                        help="Pre-run the sweep before serving (instant first paint).")
    args = parser.parse_args()

    print(f"[server] mode: {'REAL AGENTS (ANTHROPIC_API_KEY)' if _REAL else 'MOCK (deterministic)'}")
    if _WEAVE_ACTIVE:
        print(f"[server] Weave tracing ON -> {_WEAVE_URL or '(set WEAVE_ENTITY for a direct link)'}")
    else:
        print("[server] Weave tracing OFF (set WANDB_API_KEY in .env to trace agent calls)")
    if args.warm:
        print("[server] warming buyer-journey audit...")
        get_trace()

    httpd = ThreadingHTTPServer((args.host, args.port), partial(Handler))
    url = f"http://{args.host}:{args.port}"
    print("=== Trust Agentic Commerce :: visual demo ===")
    print(f"Open {url}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] shutting down.")
        httpd.shutdown()


if __name__ == "__main__":
    main()

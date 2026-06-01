"""
app/server.py -- the VISUAL DEMO server (zero extra dependencies).

OWNER: Glue

A tiny stdlib http.server that powers the buyer-journey UI in app/web/:

  GET  /                   -> serves the single-page visualization (app/web)
  GET  /api/run            -> LIVE-RUNS the journey audit over the REAL backend
                              (planner fan-out -> per-seller isolated scout -> the
                              4 security sub-agents -> concierge adjudication) and
                              returns the full data-flow trace as JSON.
                              ?level=L   contamination level of the real sweep data
                                         (0.0 / 0.2 / 0.4 / 0.6)
                              ?fresh=1   bust the cache + log a NEW Weave trace
  GET  /api/checks         -> the four blue security sub-agent definitions
  GET  /api/tracing        -> Weave status + dashboard URL

The trace is produced by app/demo_engine.build_trace, which drives the team's real
agents (blue/scout_agent + blue/concierge_agent) over data/stores. MOCK-FIRST:
with no ANTHROPIC_API_KEY the sub-agents use deterministic heuristics (runs
identically on a fresh clone); set ANTHROPIC_API_KEY to run them LIVE on Claude.
Results are cached per contamination level; the Re-run button passes fresh=1.

    python -m app.server            # then open http://localhost:8000
    python -m app.server --port 8011 --warm

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

    # override=True so the repo .env wins over an empty/stale ANTHROPIC_API_KEY
    # exported in the shell (which would otherwise force mock mode).
    load_dotenv(ROOT / ".env", override=True)
except Exception:
    pass

from app.demo_engine import DEFAULT_SCENARIO, build_trace  # noqa: E402
from tracing import init_tracing  # noqa: E402

# Activate Weave once at import. Every @traced agent step (planner fan-out, each
# per-seller scout, the four sub-agents, the concierge) is logged to the Weave
# project so you can watch every agent action when the journey runs.
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


WARM_LEVELS = [0.0, 0.2, 0.4, 0.6]
WARM_CATEGORIES = ["Beauty", "Electronics", "Sports & Outdoors",
                   "Health & Household", "All"]


def warm_all_levels() -> None:
    """Populate the cache for the common selector paths so switches are instant:
    every category at the default level, plus the default category across all
    levels. Rarer combos lazy-load once on first use. Runs sequentially in a
    background daemon thread (each run already parallelizes its isolated scouts)."""
    dft_level = DEFAULT_SCENARIO.get("level", 0.4)
    dft_cat = DEFAULT_SCENARIO.get("category", "Beauty")
    combos = ([(dft_level, c) for c in WARM_CATEGORIES]
              + [(lvl, dft_cat) for lvl in WARM_LEVELS])
    seen = set()
    for lvl, cat in combos:
        if (lvl, cat) in seen:
            continue
        seen.add((lvl, cat))
        try:
            get_trace(level=lvl, category=cat)
            print(f"[server] warmed {cat} @ {lvl:.0%}")
        except Exception as exc:  # never let warming kill the server
            print(f"[server] warm {cat} @ {lvl:.0%} failed: {exc}")


def get_trace(fresh: bool = False, level: float | None = None,
              category: str | None = None) -> dict:
    """Run (or fetch cached) the full buyer-journey audit and return its trace.

    fresh=True re-executes the whole pipeline (concierge dispatch -> per-seller
    scout -> the four sub-agents for every store), which logs a NEW Weave trace —
    so the Re-run button produces a fresh set of agent actions you can watch.
    `category` focuses the audit on one product type (None/All = full marketplace).
    """
    lvl = DEFAULT_SCENARIO.get("level", 0.4) if level is None else level
    cat = DEFAULT_SCENARIO.get("category") if category is None else category
    key = f"L{lvl}|C{cat}"
    with _CACHE_LOCK:
        if not fresh and key in _CACHE:
            return _CACHE[key]
    trace = build_trace({"level": lvl, "category": cat})
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
            l_raw = (qs.get("level") or [None])[0]
            try:
                level = float(l_raw) if l_raw is not None else None
            except ValueError:
                level = None
            category = (qs.get("category") or [None])[0]
            try:
                self._send_json(get_trace(fresh=fresh, level=level, category=category))
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
                        help="Background-warm every contamination level so selector switches are instant.")
    args = parser.parse_args()

    _live = bool(os.getenv("ANTHROPIC_API_KEY"))
    print(f"[server] mode: {'LIVE CLAUDE (anthropic)' if _live else 'MOCK (deterministic heuristics)'}"
          " — driving blue/scout_agent + blue/concierge_agent over data/stores")
    if _WEAVE_ACTIVE:
        print(f"[server] Weave tracing ON -> {_WEAVE_URL or '(set WEAVE_ENTITY for a direct link)'}")
    else:
        print("[server] Weave tracing OFF (set WANDB_API_KEY in .env to trace agent calls)")
    if args.warm:
        print("[server] warming all contamination levels in the background...")
        threading.Thread(target=warm_all_levels, daemon=True).start()

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

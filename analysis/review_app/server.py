"""The Homework 4 review interface: a standard-library server over `analysis/state/`.

It loads the Module 1 traces once at startup, live from Langfuse by default, and reads
the state files on every request so proposals added while the reviewer works appear on
the next poll. It binds to localhost and sets no CORS headers, because its POST routes
change labels and it should not accept requests from other sites.

Run it from the repository root:

    uv run python -m analysis.review_app.server
    uv run python -m analysis.review_app.server --port 8023

Add `--source export` only when Langfuse is unavailable, and record the reason in
`analysis/report/interface_comparison.md`.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from analysis.helpers import langfuse_io
from analysis.review_app import conversations as trace_data
from analysis.review_app import sampling, store

UI = Path(__file__).resolve().parent / "ui" / "index.html"


class Review:
    """The trace data loaded at startup, indexed for the request handlers."""

    def __init__(self, conversations: list[dict[str, Any]], source: str) -> None:
        self.source = source
        self.conversations = conversations
        self.by_session = {c["session_id"]: c for c in conversations}
        self.by_trace = {t["trace_id"]: c for c in conversations for t in c["turns"]}
        self.answer_keys = trace_data.load_answer_keys()
        self.reference = trace_data.load_reference()

    def context(self, trace_id: str) -> dict[str, Any]:
        conversation = self.by_trace.get(trace_id)
        if conversation is None:
            raise store.ReviewError(f"unknown trace: {trace_id}")
        return store.trace_context(conversation, trace_id)

    def summaries(self) -> list[dict[str, Any]]:
        return [
            {
                "session_id": c["session_id"],
                "scenario_id": c["scenario_id"],
                "role": c["role"],
                "turns": [t["trace_id"] for t in c["turns"]],
            }
            for c in self.conversations
        ]

    def state(self) -> dict[str, Any]:
        manifest = sampling.load_manifest()
        sample = {
            entry["session_id"]: {"batch": batch["name"], "reason": entry["reason"]}
            for batch in manifest["batches"]
            for entry in batch["conversations"]
        }
        return {
            "source": self.source,
            "langfuse_configured": langfuse_io.is_configured(),
            "annotations": store.annotations(),
            "modes": store.modes(),
            "suggestions": store.suggestions(),
            "labels": store.live_labels(),
            "sample": sample,
            "batch_order": [batch["name"] for batch in manifest["batches"]],
            "dimension": manifest.get("dimension"),
            "progress": store.progress(manifest),
        }

    def conversation(self, session_id: str) -> dict[str, Any] | None:
        conversation = self.by_session.get(session_id)
        if conversation is None:
            return None
        turns = [{**t, "langfuse_url": trace_data.langfuse_url(t["trace_id"])} for t in conversation["turns"]]
        return {**conversation, "turns": turns}

    def post(self, path: str, body: dict[str, Any]) -> Any:
        if path == "/api/annotations":
            return store.save_annotation(self.context(body["trace_id"]), body.get("note", ""), body.get("quote", ""))
        if path == "/api/modes":
            return store.save_mode(body)
        if path == "/api/modes/assign":
            return store.assign_note(body["annotation_id"], body["mode_id"], bool(body["assigned"]))
        if path == "/api/labels":
            return store.save_label(self.context(body["trace_id"]), body["mode"], bool(body["present"]),
                                    bool(body.get("close_negative")), body.get("evidence", ""))
        if path == "/api/labels/absent_rest":
            current = store.live_labels()
            names = [name for name, rows in current.items() if body["trace_id"] not in rows]
            return [store.save_label(self.context(body["trace_id"]), name, False) for name in names]
        if path == "/api/labels/resend":
            return store.resend_labels()
        if path == "/api/suggestions/decide":
            return store.decide_suggestion(body["id"], body["decision"], body.get("reason", ""))
        return None


class Handler(BaseHTTPRequestHandler):
    review: Review

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(self.path.split("?", 1)[0])
        if path in ("/", "/index.html"):
            body = UI.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/state":
            self._json(self.review.state())
        elif path == "/api/conversations":
            self._json(self.review.summaries())
        elif path == "/api/reference":
            self._json(self.review.reference)
        elif path == "/api/labels/verify":
            try:
                self._json(store.verify_labels())
            except Exception as exc:  # noqa: BLE001 - shown to the reviewer as a failed check
                self._json({"error": f"could not read Langfuse: {exc}"}, status=502)
        elif path.startswith("/api/conversation/"):
            conversation = self.review.conversation(path.rsplit("/", 1)[1])
            self._json(conversation or {"error": "unknown conversation"}, 200 if conversation else 404)
        elif path.startswith("/api/answer_key/"):
            key = self.review.answer_keys.get(path.rsplit("/", 1)[1])
            self._json(key or {"error": "no answer key for this scenario"}, 200 if key else 404)
        else:
            self._json({"error": f"unknown path: {path}"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            result = self.review.post(path, body)
        except store.ReviewError as exc:
            self._json({"error": str(exc)}, 400)
        except (KeyError, TypeError, ValueError) as exc:
            self._json({"error": f"bad request: {exc}"}, 400)
        else:
            if result is None:
                self._json({"error": f"cannot POST to {path}"}, 404)
            else:
                self._json(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8022)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--source", choices=("langfuse", "export"), default="langfuse")
    args = parser.parse_args()

    print(f"Loading traces from {args.source}...", flush=True)
    conversations = trace_data.load_conversations(args.source)
    traces = sum(len(c["turns"]) for c in conversations)
    print(f"Loaded {len(conversations)} conversations and {traces} traces.", flush=True)

    Handler.review = Review(conversations, args.source)
    print(f"Review interface: http://{args.host}:{args.port}/", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()

"""Rebuild complete conversations from Module 1 traces for human review.

Cartwheel creates one Langfuse trace per user turn, and the shared normalizer keeps
only each turn's final reply: generation outputs are empty in these traces, so the
text and thinking the agent produced before a tool call appear only in the last
generation's input. This module recovers those steps in the order the model produced
them and groups the turns of each `cartwheel.session_id` chronologically.

The Langfuse trace identifier stays on every turn, so a judgment can be written back
to the trace the reviewer read.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from analysis.helpers import langfuse_io
from analysis.helpers.normalization import _text, normalize_trace
from observability.instrument import load_env

REPO = Path(__file__).resolve().parents[2]
EXPORT = REPO / "traces" / "support_traces.json"
SCENARIOS = REPO / "scenarios" / "support_scenarios.jsonl"
DATABASE = REPO / "data" / "cartwheel.db"
POLICIES = REPO / "data" / "policies"
SPEC = REPO / "SPEC.md"

SCENARIO_PREFIX = "support-"
RETRIEVAL_TOOLS = {"search_help_center", "get_policy"}


def _parse(value: Any) -> Any:
    """Decode a tool payload, which may be JSON or a Python repr in the model input."""
    if not isinstance(value, str):
        return value
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(value)
        except (ValueError, SyntaxError):
            continue
    return value


def _parts(message: Any) -> list[dict[str, Any]]:
    parts = message.get("parts") if isinstance(message, dict) else None
    return [part for part in parts or [] if isinstance(part, dict)]


def _tool_step(name: Any, arguments: Any, result: Any) -> dict[str, Any]:
    result = _parse(result)
    failed = isinstance(result, dict) and result.get("ok") is False
    error = {"code": result.get("error"), "reason": result.get("reason")} if failed else None
    return {"kind": "tool", "name": str(name), "arguments": _parse(arguments), "result": result, "error": error}


def _take_span(spans: list[dict[str, Any]], name: Any, arguments: Any) -> dict[str, Any] | None:
    """Remove and return the tool span for a call, preferring identical arguments."""
    same_name = [span for span in spans if span["name"] == name]
    for span in same_name:
        if _parse(span["input"]) == arguments:
            spans.remove(span)
            return span
    if same_name:
        spans.remove(same_name[0])
        return same_name[0]
    return None


def rebuild_steps(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one turn's thinking, agent text, and tool calls in the model's order."""
    by_start = lambda observation: observation.get("start_time") or ""  # noqa: E731
    observations = record["observations"]
    generations = sorted((o for o in observations if o["type"] == "GENERATION"), key=by_start)
    remaining = sorted((o for o in observations if o["type"] == "TOOL"), key=by_start)

    messages = generations[-1]["input"] if generations else None
    messages = messages if isinstance(messages, list) else []
    user_at = [i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") == "user"]
    this_turn = messages[user_at[-1] + 1:] if user_at else []
    responses = {
        part.get("id"): part.get("response")
        for message in this_turn
        for part in _parts(message)
        if part.get("type") == "tool_call_response"
    }

    steps: list[dict[str, Any]] = []
    for message in this_turn:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for part in _parts(message):
            kind = part.get("type")
            if kind == "thinking" and str(part.get("thinking") or "").strip():
                steps.append({"kind": "thinking", "text": part["thinking"]})
            elif kind == "text" and str(part.get("content") or "").strip():
                steps.append({"kind": "agent_text", "text": part["content"]})
            elif kind == "tool_call":
                arguments = _parse(part.get("arguments"))
                span = _take_span(remaining, part.get("name"), arguments)
                result = span["output"] if span else responses.get(part.get("id"))
                steps.append(_tool_step(part.get("name"), arguments, result))
    # A tool span missing from the model input still has to reach the reviewer.
    steps.extend(_tool_step(span["name"], span["input"], span["output"]) for span in remaining)
    return steps


def _system_prompt(record: dict[str, Any]) -> str:
    generations = sorted(
        (o for o in record["observations"] if o["type"] == "GENERATION"),
        key=lambda o: o.get("start_time") or "",
    )
    for generation in generations:
        messages = generation["input"] if isinstance(generation["input"], list) else []
        for message in messages:
            if isinstance(message, dict) and message.get("role") == "system":
                return "\n".join(str(p.get("content") or "") for p in _parts(message))
    return ""


def _session_value(prompt: str, label: str) -> str | None:
    match = re.search(rf"^- {label}: (.+)$", prompt, flags=re.MULTILINE)
    value = match.group(1).strip() if match else None
    return None if value in (None, "none") else value


def world_facts() -> dict[str, Any]:
    """Read the facts a run cannot change: the world's date and the store names."""
    if not DATABASE.exists():
        return {"as_of": None, "stores": {}}
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = 'world_asof'").fetchone()
        stores = {str(i): name for i, name in connection.execute("SELECT id, name FROM stores")}
    finally:
        connection.close()
    return {"as_of": row[0] if row else None, "stores": stores}


def build_conversations(records: list[dict[str, Any]], world: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Group normalized traces into conversations, each with its turns in time order."""
    world = world or {"as_of": None, "stores": {}}
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        scenario = str(record["meta"].get("scenario_id") or "")
        if scenario.startswith(SCENARIO_PREFIX):
            sessions[str(record["meta"].get("session_id") or record["trace_id"])].append(record)

    conversations = []
    for session_id, group in sessions.items():
        group.sort(key=lambda record: record.get("timestamp") or "")
        prompt = _system_prompt(group[0])
        store_id = _session_value(prompt, "Store id")
        conversations.append(
            {
                "session_id": session_id,
                "scenario_id": group[0]["meta"]["scenario_id"],
                "role": group[0]["meta"].get("role"),
                "user_id": _session_value(prompt, "User id"),
                "store_id": store_id,
                "store_name": world["stores"].get(store_id) if store_id else None,
                "as_of": world["as_of"],
                "system_prompt": prompt,
                "turns": [
                    {
                        "trace_id": record["trace_id"],
                        "turn": number,
                        "timestamp": record.get("timestamp"),
                        "models": record.get("models") or [],
                        "user": _text(record.get("input")),
                        "steps": rebuild_steps(record),
                        "reply": _text(record.get("output")),
                    }
                    for number, record in enumerate(group, 1)
                ],
            }
        )
    conversations.sort(key=lambda conversation: conversation["scenario_id"])
    return conversations


def features(conversation: dict[str, Any]) -> dict[str, float]:
    """Structural features for clustering. None of them looks at whether a turn failed."""
    tools = [s for turn in conversation["turns"] for s in turn["steps"] if s["kind"] == "tool"]
    names = {tool["name"] for tool in tools}
    words = sum(len((turn["user"] + " " + turn["reply"]).split()) for turn in conversation["turns"])
    values: dict[str, float] = {
        "turn_count": len(conversation["turns"]),
        "tool_call_count": len(tools),
        "distinct_tools": len(names),
        "has_retrieval": float(bool(names & RETRIEVAL_TOOLS)),
        "words": words,
    }
    return {**values, **{f"tool:{name}": 1.0 for name in names}}


def load_records(source: str = "langfuse", export: Path = EXPORT) -> list[dict[str, Any]]:
    """Load normalized per-turn traces. The export is a fallback for when Langfuse is down."""
    load_env()
    if source == "langfuse":
        return langfuse_io.fetch_traces()
    if source == "export":
        return [normalize_trace(trace) for trace in json.loads(export.read_text())["traces"]]
    raise ValueError(f"unknown trace source: {source}")


def load_conversations(source: str = "langfuse", export: Path = EXPORT) -> list[dict[str, Any]]:
    conversations = build_conversations(load_records(source, export), world_facts())
    if not conversations:
        raise ValueError(f"no {SCENARIO_PREFIX}* traces found in {source}")
    return conversations


def load_answer_keys(path: Path = SCENARIOS) -> dict[str, dict[str, Any]]:
    """Each scenario's expected outcome, served only when the reviewer asks for it."""
    if not path.exists():
        return {}
    keys = {}
    for line in path.read_text().splitlines():
        scenario = json.loads(line)
        keys[scenario["id"]] = {
            "expected": scenario["expected"],
            "tuple": scenario["tuple"],
            "scenario_group": scenario["scenario_group"],
            "data_quality_case_id": scenario.get("data_quality_case_id"),
        }
    return keys


def load_reference() -> dict[str, Any]:
    """The policy documents and the specification, for the reference panel."""
    policies = []
    for path in sorted(POLICIES.glob("*.md")):
        text = path.read_text()
        title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        policies.append({"id": path.stem, "title": title, "text": text})
    return {"policies": policies, "spec": SPEC.read_text() if SPEC.exists() else ""}


def langfuse_url(trace_id: str) -> str:
    host = os.environ.get("LANGFUSE_HOST") or "http://localhost:3000"
    project = os.environ.get("LANGFUSE_PROJECT_ID") or "cartwheel-dev"
    return f"{host.rstrip('/')}/project/{project}/traces/{trace_id}"

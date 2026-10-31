"""Review state: open codes, the taxonomy, suggestions, and binary judgments.

Everything is a plain file under `analysis/state/`, read fresh on each request, so the
coding agent can add proposals while the reviewer works. Langfuse holds the accepted
judgments as scores; `analysis/state/labels/` keeps the matching local record.

Three rules from the handout are enforced here rather than left to the interface:
a mode must trace back to a human note, a rejected suggestion stays on disk with its
reason, and editing an open code keeps the earlier text.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

from analysis.helpers import _state, langfuse_io, tools

LOCK = threading.RLock()

NO_FAILURE = "no failure observed"
STATUSES = ("proposed", "candidate", "confirmed", "rejected", "merged")
EVALUATORS = ("", "code", "llm_judge")
MODE_FIELDS = ("name", "status", "definition", "boundary", "nearest_mode", "requirement",
               "evaluator_type", "likely_fix", "merged_into")
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


class ReviewError(ValueError):
    """A request the review rules refuse; its message is shown to the reviewer."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def trace_context(conversation: dict[str, Any], trace_id: str) -> dict[str, Any]:
    """The identifiers stored beside a note, label, or suggestion for one trace."""
    turn = next(t for t in conversation["turns"] if t["trace_id"] == trace_id)
    return {
        "trace_id": trace_id,
        "session_id": conversation["session_id"],
        "scenario_id": conversation["scenario_id"],
        "turn": turn["turn"],
    }


# ---------------------------------------------------------------------------
# open codes
# ---------------------------------------------------------------------------


def annotations() -> list[dict[str, Any]]:
    data = _state.read_json(_state.state_path("annotations.json"), default={"annotations": []})
    return data.get("annotations", []) if isinstance(data, dict) else data


def _write_annotations(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row["author"] = row["source"]  # the field name in the starter's annotations
    _state.write_json(_state.state_path("annotations.json"), {"annotations": rows})


def save_annotation(context: dict[str, Any], note: str, quote: str = "", source: str = "human") -> dict[str, Any]:
    """Create or update the open code for one trace, keeping any earlier text in `history`."""
    note, quote = note.strip(), quote.strip()
    with LOCK:
        rows = annotations()
        row = next((r for r in rows if r["trace_id"] == context["trace_id"]), None)
        if row is None:
            row = {"id": context["trace_id"], **context, "note": "", "quote": "", "source": source,
                   "created_at": _now(), "history": []}
            rows.append(row)
        if row["note"] and row["note"] != note:
            row["history"].append({"note": row["note"], "quote": row["quote"], "source": row["source"],
                                   "saved_at": row["updated_at"]})
            row["source"] = source
        row.update(note=note, quote=quote, no_failure=note.lower() == NO_FAILURE, updated_at=_now())
        _write_annotations(rows)
        return row


def reviewed_traces() -> set[str]:
    return {row["trace_id"] for row in annotations() if row["note"]}


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------


def modes() -> list[dict[str, Any]]:
    return tools._load_patterns().get("modes", [])


def _write_modes(rows: list[dict[str, Any]]) -> None:
    for row in rows:  # the field names `failure_report` reads
        row["requirement_source"] = row["requirement"]
        row["example_trace_ids"] = sorted({*row["created_from"], *row["positive_trace_ids"]})
    _state.write_json(_state.state_path("patterns.json"), {"modes": rows})


def _check_name(name: str, rows: list[dict[str, Any]], current: dict[str, Any] | None) -> None:
    if not _NAME.match(name):
        raise ReviewError(f"'{name}' is not snake_case")
    if any(row["name"] == name and row is not current for row in rows):
        raise ReviewError(f"a mode named '{name}' already exists")
    existing = _state.read_jsonl(_state.state_path("labels", f"{name}.jsonl"))
    if any(not _TRACE_ID.match(str(row.get("trace_id"))) for row in existing):
        raise ReviewError(f"'{name}' is taken by the starter's demonstration labels; choose another name")


def save_mode(fields: dict[str, Any], proposed_by: str | None = None) -> dict[str, Any]:
    """Create a mode, or update one by `id`, recording each changed field in `revisions`."""
    with LOCK:
        rows = modes()
        row = next((r for r in rows if r.get("id") == fields.get("id")), None) if fields.get("id") else None
        creating = row is None
        if creating:
            row = {"id": f"m-{len(rows) + 1}", "name": "", "status": "candidate",
                   "definition": "", "boundary": "", "nearest_mode": "", "requirement": "", "evaluator_type": "",
                   "likely_fix": "", "merged_into": "", "created_from": [], "positive_trace_ids": [],
                   "rejected_trace_ids": [], "proposed_by": proposed_by or "human", "revisions": [],
                   "created_at": _now()}
        changes = {key: fields[key] for key in MODE_FIELDS if key in fields and fields[key] != row.get(key)}
        if "created_from" in fields and creating:
            row["created_from"] = list(fields["created_from"])
        if "name" in changes or creating:
            _check_name(changes.get("name", row["name"]), rows, None if creating else row)
            if not creating and tools._load_labels(row["name"]):
                raise ReviewError("this mode already has labels, so its name is locked")
        if changes.get("status", row["status"]) not in STATUSES:
            raise ReviewError(f"unknown status: {changes['status']}")
        if changes.get("evaluator_type", row["evaluator_type"]) not in EVALUATORS:
            raise ReviewError(f"unknown evaluator type: {changes['evaluator_type']}")
        if changes.get("status") == "confirmed" and not row["created_from"]:
            raise ReviewError("a final mode needs at least one supporting note of yours")
        if not creating:
            row["revisions"].extend(
                {"field": key, "old": row.get(key), "new": value, "at": _now()} for key, value in changes.items())
        row.update(changes)
        if creating:
            rows.append(row)
        _write_modes(rows)
        return row


def propose_mode(name: str, definition: str, created_from: list[str], boundary: str = "",
                 **details: str) -> dict[str, Any]:
    """Add the agent's proposed grouping. It must rest on notes the reviewer wrote."""
    known = {row["id"] for row in annotations() if row["source"] == "human" and not row.get("no_failure")}
    missing = [note for note in created_from if note not in known]
    if not created_from or missing:
        raise ReviewError(f"a proposal must cite human notes; not found: {missing}")
    return save_mode({**details, "name": name, "definition": definition, "boundary": boundary, "status": "proposed",
                      "created_from": created_from}, proposed_by="claude")


def assign_note(annotation_id: str, mode_id: str, assigned: bool) -> dict[str, Any]:
    """Add a note to a mode's supporting evidence, or remove it."""
    with LOCK:
        rows = modes()
        row = next((r for r in rows if r["id"] == mode_id), None)
        if row is None:
            raise ReviewError("unknown mode")
        note = next((a for a in annotations() if a["id"] == annotation_id), None)
        if note is None:
            raise ReviewError("unknown note")
        if assigned and note["source"] != "human":
            raise ReviewError("only a note you wrote can support a mode; rewrite it in your own words first")
        support = [a for a in row["created_from"] if a != annotation_id]
        row["created_from"] = support + [annotation_id] if assigned else support
        _write_modes(rows)
        return row


# ---------------------------------------------------------------------------
# judgments
# ---------------------------------------------------------------------------


def score_id(trace_id: str, mode: str) -> str:
    """One stable id per trace and mode, so changing a judgment replaces the score."""
    return f"{trace_id}-{mode}"


def _send_score(trace_id: str, mode: str, label: int, comment: str, client: Any | None) -> str | None:
    """Send the score to Langfuse. Return the error text, or None once it has been sent."""
    if client is None and not langfuse_io.is_configured():
        return "Langfuse is not configured"
    try:
        client = client or langfuse_io._client()
        client.create_score(name=mode, value=label, trace_id=trace_id, score_id=score_id(trace_id, mode),
                            data_type="NUMERIC", comment=comment or None)
        client.flush()
    except Exception as exc:  # noqa: BLE001 - the local record must survive a Langfuse outage
        return str(exc)
    return None


def _confirmed_names() -> list[str]:
    return [row["name"] for row in modes() if row["status"] == "confirmed"]


def save_label(context: dict[str, Any], mode: str, present: bool, close_negative: bool = False, evidence: str = "",
               source: str = "human", client: Any | None = None) -> dict[str, Any]:
    """Record one present or absent judgment in Langfuse and in `labels/<mode>.jsonl`.

    The label file is append-only for its content: a change adds a new line and marks
    the earlier line `superseded_by`, which `tools._load_labels` already understands.
    """
    if mode not in _confirmed_names():
        raise ReviewError(f"'{mode}' is not a final mode")
    label = 1 if present else 0
    error = _send_score(context["trace_id"], mode, label, evidence, client)
    with LOCK:
        path = _state.state_path("labels", f"{mode}.jsonl")
        rows = _state.read_jsonl(path)
        previous = [r for r in rows if r["trace_id"] == context["trace_id"]]
        record = {**context, "mode": mode, "label": label, "close_negative": bool(close_negative and not present),
                  "evidence": evidence.strip(), "source": source, "ts": _now(),
                  "label_id": f"{context['trace_id']}#{len(previous)}", "score_id": score_id(context["trace_id"], mode),
                  "langfuse_sent": error is None}
        for row in previous:
            row.setdefault("superseded_by", record["label_id"])
        _state.write_jsonl(path, [*rows, record])
    return {**record, "langfuse_error": error}


def live_labels() -> dict[str, dict[str, dict[str, Any]]]:
    return {name: {row["trace_id"]: row for row in tools._load_labels(name)} for name in _confirmed_names()}


def resend_labels(client: Any | None = None) -> dict[str, Any]:
    """Send every current judgment again. The stable score ids make this safe to repeat."""
    sent, errors = 0, []
    for name, rows in live_labels().items():
        for trace_id, row in rows.items():
            error = _send_score(trace_id, name, row["label"], row.get("evidence", ""), client)
            if error:
                errors.append(error)
                continue
            sent += 1
            if not row.get("langfuse_sent"):
                with LOCK:
                    path = _state.state_path("labels", f"{name}.jsonl")
                    stored = _state.read_jsonl(path)
                    for candidate in stored:
                        if candidate.get("label_id") == row.get("label_id"):
                            candidate["langfuse_sent"] = True
                    _state.write_jsonl(path, stored)
    return {"sent": sent, "errors": errors[:3], "failed": len(errors)}


def verify_labels(client: Any | None = None) -> dict[str, Any]:
    """Compare the current local judgments with the scores Langfuse holds."""
    client = client or langfuse_io._client()
    matched = 0
    problems: list[dict[str, Any]] = []
    labels = live_labels()
    traces = sorted({trace_id for rows in labels.values() for trace_id in rows})
    for trace_id in traces:
        scores = {s["name"]: s["value"] for s in langfuse_io.read_label_scores(trace_id, client=client)}
        for name, rows in labels.items():
            if trace_id not in rows:
                continue
            if scores.get(name) == rows[trace_id]["label"]:
                matched += 1
            else:
                problems.append({"trace_id": trace_id, "mode": name, "local": rows[trace_id]["label"],
                                 "langfuse": scores.get(name)})
    return {"matched": matched, "problems": problems[:20], "problem_count": len(problems)}


# ---------------------------------------------------------------------------
# suggestions
# ---------------------------------------------------------------------------


def suggestions() -> list[dict[str, Any]]:
    return _state.read_json(_state.state_path("suggestions.json"), default=[])


def _write_suggestions(rows: list[dict[str, Any]]) -> None:
    _state.write_json(_state.state_path("suggestions.json"), rows)


def add_suggestions(search: str, mode: str | None, signal: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add one search's hits as pending. A hit is a retrieval signal, never a label."""
    with LOCK:
        rows = suggestions()
        added = []
        for item in items:
            added.append({"id": f"s-{len(rows) + len(added) + 1}", "search": search, "mode": mode, "signal": signal,
                          "status": "pending", "decision_reason": "", "proposed_by": "claude", "created_at": _now(),
                          **{key: item.get(key, "") for key in ("trace_id", "session_id", "scenario_id", "turn",
                                                                 "quote", "reason")}})
        _write_suggestions([*rows, *added])
        return added


def decide_suggestion(suggestion_id: str, decision: str, reason: str = "", client: Any | None = None) -> dict[str, Any]:
    """Accept or reject one suggestion, or change an earlier decision, keeping it in `history`.

    A rejection needs the boundary that excludes it.
    """
    if decision not in ("accepted", "rejected"):
        raise ReviewError("the decision must be accepted or rejected")
    if decision == "rejected" and not reason.strip():
        raise ReviewError("say why this suggestion falls outside the mode")
    with LOCK:
        rows = suggestions()
        row = next((r for r in rows if r["id"] == suggestion_id), None)
        if row is None:
            raise ReviewError("unknown suggestion")
        if row["status"] != "pending":
            row.setdefault("history", []).append({key: row.get(key) for key in ("status", "decision_reason", "decided_at")})
        row.update(status=decision, decision_reason=reason.strip(), decided_at=_now())
        _write_suggestions(rows)

        context = {key: row[key] for key in ("trace_id", "session_id", "scenario_id", "turn")}
        all_modes = modes()
        mode = next((m for m in all_modes if m["name"] == row["mode"]), None)
        if mode is not None:
            key, other = ("positive_trace_ids", "rejected_trace_ids") if decision == "accepted" \
                else ("rejected_trace_ids", "positive_trace_ids")
            if row["trace_id"] not in mode[key]:
                mode[key].append(row["trace_id"])
            if row["trace_id"] in mode[other]:
                mode[other].remove(row["trace_id"])
            _write_modes(all_modes)
    if decision == "accepted":
        if row["trace_id"] not in reviewed_traces():
            text = row["reason"] or f"accepted suggestion for {row['mode']}"
            save_annotation(context, text, row["quote"], source="accepted_suggestion")
        if row["mode"] in _confirmed_names():
            save_label(context, row["mode"], True, evidence=reason or row["reason"], source="accepted_suggestion",
                       client=client)
    return row


# ---------------------------------------------------------------------------
# progress
# ---------------------------------------------------------------------------


def progress(manifest: dict[str, Any]) -> dict[str, Any]:
    """Coverage, incomplete judgments, sample fractions, and new modes per batch."""
    notes = annotations()
    reviewed = {row["trace_id"] for row in notes if row["note"]}
    all_modes = modes()
    labels = live_labels()
    final_names = list(labels)

    batches, sampled = [], []
    batch_of: dict[str, str] = {}
    for batch in manifest.get("batches", []):
        traces = [(entry, trace_id) for entry in batch["conversations"] for trace_id in entry["trace_ids"]]
        sampled.extend(traces)
        for _, trace_id in traces:
            batch_of[trace_id] = batch["name"]
        batches.append({"name": batch["name"], "method": batch["method"], "target": batch["target_conversations"],
                        "conversations": len(batch["conversations"]), "traces": len(traces),
                        "reviewed": sum(trace_id in reviewed for _, trace_id in traces)})
    sampled_ids = [trace_id for _, trace_id in sampled]
    entries = {id(entry): entry for entry, _ in sampled}.values()

    incomplete = []
    for entry, trace_id in sampled:
        missing = [name for name in final_names if trace_id not in labels[name]]
        if trace_id in reviewed and missing:
            incomplete.append({"trace_id": trace_id, "session_id": entry["session_id"],
                               "scenario_id": entry["scenario_id"], "turn": entry["trace_ids"].index(trace_id) + 1,
                               "missing": missing})

    note_batch = {row["id"]: batch_of.get(row["trace_id"]) for row in notes}
    order = [batch["name"] for batch in batches]
    discovered: dict[str, list[str]] = {name: [] for name in order}
    mode_rows = []
    for mode in all_modes:
        rows = labels.get(mode["name"], {})
        in_sample = [rows[t] for t in sampled_ids if t in rows]
        present = [r["trace_id"] for r in in_sample if r["label"] == 1]
        close = [r["trace_id"] for r in in_sample if r.get("close_negative")]
        positives = sorted({*present, *mode.get("positive_trace_ids", [])})
        origins = [note_batch[a] for a in mode["created_from"] if note_batch.get(a) in discovered]
        if origins and mode["status"] in ("candidate", "confirmed"):
            discovered[min(origins, key=order.index)].append(mode["name"])
        mode_rows.append(
            {
                "id": mode["id"],
                "name": mode["name"],
                "status": mode["status"],
                "present": len(present),
                "absent": len(in_sample) - len(present),
                "close_negatives": len(close),
                "missing": sum(t in reviewed and t not in rows for t in sampled_ids) if mode["status"] == "confirmed" else None,
                "fraction": round(len(present) / len(in_sample), 4) if in_sample else None,
                "positive_trace_ids": positives,
                "close_negative_trace_ids": close,
                "checklist": {
                    "definition": bool(mode["definition"].strip()),
                    "three_positives": len(positives) >= 3,
                    "three_close_negatives": len(close) >= 3,
                    "human_notes": bool(mode["created_from"]),
                    "boundary": bool(mode["boundary"].strip()),
                    "evaluator": bool(mode["evaluator_type"]),
                    "requirement": bool(mode["requirement"].strip()),
                },
            }
        )

    unsent = sum(not row.get("langfuse_sent") for rows in labels.values() for row in rows.values())
    return {
        "totals": {
            "conversations": len(list(entries)),
            "traces": len(sampled_ids),
            "traces_reviewed": sum(t in reviewed for t in sampled_ids),
            "no_failure": sum(r.get("no_failure", False) and r["trace_id"] in sampled_ids for r in notes),
            "conversations_complete": sum(all(t in reviewed for t in e["trace_ids"]) for e in entries),
        },
        "batches": batches,
        "modes": mode_rows,
        "incomplete": incomplete,
        "discovery": [{"batch": name, "new_modes": discovered[name]} for name in order],
        "labels_unsent": unsent,
    }

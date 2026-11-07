"""Select the conversations reviewed in Homework 4 and record why each was picked.

The handout counts traces, and Cartwheel creates one trace per turn. A reviewer reads
the whole conversation anyway, and Homework 5 evaluates one record per conversation,
so these batches draw conversations and every turn of a drawn conversation is
reviewed. One hundred conversations hold about 146 traces.

Every batch is appended to `analysis/state/sample_manifest.json`. `select_traces`
in the shared helpers rewrites that file on each call, so it cannot hold four batches.

Run from the repository root:

    uv run python -m analysis.review_app.sampling start --dimension role
    uv run python -m analysis.review_app.sampling dimension
    uv run python -m analysis.review_app.sampling depth --input search.json
    uv run python -m analysis.review_app.sampling final
    uv run python -m analysis.review_app.sampling status

Add `--source export` only when Langfuse is unavailable.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis.helpers import _state, selection
from analysis.review_app import conversations as trace_data
from analysis.review_app import store

SEED = 20261030
CLUSTERS = 8

# Read in the Langfuse annotation view to plan the interface, so they stay out of the batches.
PRELIMINARY = ("support-0207", "support-0058", "support-0091", "support-0161", "support-0157",
               "support-0177", "support-0107")

UNIFORM_START, CLUSTER_REPS, DIMENSION, DEPTH, UNIFORM_FINAL = (
    "uniform_start", "cluster_representatives", "dimension", "depth_search", "uniform_final")
TARGETS = {UNIFORM_START: 15, CLUSTER_REPS: 15, DIMENSION: 30, DEPTH: 25, UNIFORM_FINAL: 15}


def _manifest_path() -> Path:
    return _state.state_path("sample_manifest.json")


def load_manifest() -> dict[str, Any]:
    """Return the manifest. A file left by `select_traces` has no batches and starts over."""
    manifest = _state.read_json(_manifest_path(), default={})
    if not isinstance(manifest, dict) or "batches" not in manifest:
        return {"source": "langfuse", "unit": "conversation; every turn (Langfuse trace) is reviewed",
                "seed": SEED, "dimension": None, "preliminary": list(PRELIMINARY), "batches": []}
    return manifest


def write_manifest(manifest: dict[str, Any]) -> None:
    _state.write_json(_manifest_path(), manifest)


def _sampled_sessions(manifest: dict[str, Any]) -> set[str]:
    return {entry["session_id"] for batch in manifest["batches"] for entry in batch["conversations"]}


def _pool(conversations: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Conversations eligible for a new batch, in a stable order."""
    used = _sampled_sessions(manifest)
    return [c for c in conversations if c["session_id"] not in used and c["scenario_id"] not in PRELIMINARY]


def _entry(conversation: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "session_id": conversation["session_id"],
        "scenario_id": conversation["scenario_id"],
        "role": conversation["role"],
        "trace_ids": [turn["trace_id"] for turn in conversation["turns"]],
        "reason": reason,
    }


def _batch(manifest: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((batch for batch in manifest["batches"] if batch["name"] == name), None)


def _add_batch(manifest: dict[str, Any], name: str, method: str, entries: list[dict[str, Any]], **extra: Any) -> None:
    if _batch(manifest, name):
        raise ValueError(f"batch '{name}' already exists; it is never redrawn")
    manifest["batches"].append(
        {
            "name": name,
            "method": method,
            "target_conversations": TARGETS[name],
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "conversations": entries,
            **extra,
        }
    )


def uniform(pool: list[dict[str, Any]], k: int, seed: int) -> list[dict[str, Any]]:
    return random.Random(seed).sample(pool, min(k, len(pool)))


def cluster_representatives(pool: list[dict[str, Any]], k: int, seed: int = SEED) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cluster on structure and take the members nearest each centroid, round robin."""
    rows = [trace_data.features(conversation) for conversation in pool]
    names = sorted({name for row in rows for name in row})
    vectors = selection._standardize([[row.get(name, 0.0) for name in names] for row in rows])
    assignment = selection._kmeans(vectors, k=CLUSTERS, seed=seed)

    members: dict[int, list[int]] = defaultdict(list)
    for index, cluster in enumerate(assignment):
        members[cluster].append(index)
    for indexes in members.values():
        center = [sum(vectors[i][d] for i in indexes) / len(indexes) for d in range(len(names))]
        indexes.sort(key=lambda i: sum((a - b) ** 2 for a, b in zip(vectors[i], center)))

    summary = [
        {
            "cluster": cluster,
            "size": len(indexes),
            "tools": dict(Counter(
                name[5:] for i in indexes for name in rows[i] if name.startswith("tool:")).most_common(4)),
        }
        for cluster, indexes in sorted(members.items())
    ]
    picks: list[dict[str, Any]] = []
    queues = {cluster: list(indexes) for cluster, indexes in members.items()}
    while len(picks) < min(k, len(pool)):
        for cluster in sorted(queues):
            if queues[cluster] and len(picks) < k:
                conversation = pool[queues[cluster].pop(0)]
                picks.append(_entry(conversation, f"cluster {cluster} of {len(queues)} (size {len(members[cluster])})"))
    return picks, summary


def across_dimension(pool: list[dict[str, Any]], dimension: str, k: int, seed: int) -> list[dict[str, Any]]:
    """Spread `k` conversations evenly across the values of one dimension."""
    keys = trace_data.load_answer_keys()

    def value_of(conversation: dict[str, Any]) -> str:
        if dimension == "role":
            return str(conversation["role"])
        return str(keys[conversation["scenario_id"]]["tuple"][dimension])

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for conversation in pool:
        groups[value_of(conversation)].append(conversation)
    rng = random.Random(seed)
    for value in sorted(groups):
        rng.shuffle(groups[value])

    picks: list[dict[str, Any]] = []
    while len(picks) < min(k, len(pool)):
        for value in sorted(groups):
            if groups[value] and len(picks) < k:
                picks.append(_entry(groups[value].pop(), f"{dimension} = {value}"))
    return picks


def start(conversations: list[dict[str, Any]], dimension: str, source: str = "langfuse") -> dict[str, Any]:
    """Record the dimension before anything is read, then draw the first two batches."""
    manifest = load_manifest()
    manifest["dimension"] = dimension
    manifest["source"] = "langfuse" if source == "langfuse" else str(trace_data.EXPORT)
    manifest["population"] = {
        "conversations": len(conversations),
        "traces": sum(len(c["turns"]) for c in conversations),
    }
    drawn = uniform(_pool(conversations, manifest), TARGETS[UNIFORM_START], SEED + 1)
    _add_batch(manifest, UNIFORM_START, "uniform over conversations",
               [_entry(c, "uniform draw") for c in drawn], seed=SEED + 1)
    picks, clusters = cluster_representatives(_pool(conversations, manifest), TARGETS[CLUSTER_REPS], SEED)
    _add_batch(manifest, CLUSTER_REPS, f"k-means on structure, k={CLUSTERS}, nearest each centroid",
               picks, seed=SEED, clusters=clusters)
    write_manifest(manifest)
    return manifest


def draw_dimension(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    manifest = load_manifest()
    dimension = manifest.get("dimension")
    if not dimension:
        raise ValueError("no dimension recorded; run `start --dimension <name>` first")
    picks = across_dimension(_pool(conversations, manifest), dimension, TARGETS[DIMENSION], SEED + 2)
    _add_batch(manifest, DIMENSION, f"even spread across {dimension}", picks, seed=SEED + 2, dimension=dimension)
    write_manifest(manifest)
    return manifest


def draw_final(conversations: list[dict[str, Any]]) -> dict[str, Any]:
    """Draw the last uniform batch, which checks whether new modes still appear."""
    manifest = load_manifest()
    drawn = uniform(_pool(conversations, manifest), TARGETS[UNIFORM_FINAL], SEED + 3)
    _add_batch(manifest, UNIFORM_FINAL, "uniform over conversations, after the taxonomy draft",
               [_entry(c, "uniform draw") for c in drawn], seed=SEED + 3)
    write_manifest(manifest)
    return manifest


def add_depth(conversations: list[dict[str, Any]], search: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Record one search: its hits become pending suggestions, and new conversations join the depth batch.

    A similarity score or filter only retrieves a trace. The reviewer decides each one.
    """
    by_trace = {turn["trace_id"]: c for c in conversations for turn in c["turns"]}
    manifest = load_manifest()
    batch = _batch(manifest, DEPTH)
    if batch is None:
        _add_batch(manifest, DEPTH, "depth searches for candidate modes and close negatives", [])
        batch = _batch(manifest, DEPTH)
    used = _sampled_sessions(manifest)
    items = []
    for item in search["suggestions"]:
        conversation = by_trace[item["trace_id"]]
        items.append({**item, **store.trace_context(conversation, item["trace_id"])})
        if conversation["session_id"] not in used and conversation["scenario_id"] not in PRELIMINARY:
            batch["conversations"].append(_entry(conversation, f"search: {search['search']}"))
            used.add(conversation["session_id"])
    write_manifest(manifest)
    return manifest, store.add_suggestions(search["search"], search.get("mode"), search.get("signal", ""), items)


def report(manifest: dict[str, Any]) -> str:
    lines = []
    for batch in manifest["batches"]:
        entries = batch["conversations"]
        traces = sum(len(entry["trace_ids"]) for entry in entries)
        roles = Counter(entry["role"] for entry in entries)
        lines.append(f"{batch['name']}: {len(entries)}/{batch['target_conversations']} conversations, "
                     f"{traces} traces, {dict(sorted(roles.items()))}")
    total = sum(len(entry["trace_ids"]) for batch in manifest["batches"] for entry in batch["conversations"])
    lines.append(f"total: {len(_sampled_sessions(manifest))} conversations, {total} traces")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=("langfuse", "export"), default="langfuse")
    commands = parser.add_subparsers(dest="command", required=True)
    first = commands.add_parser("start", help="record the dimension and draw the first two batches")
    first.add_argument("--dimension", required=True, help="role, or any field of a scenario's tuple")
    commands.add_parser("dimension", help="draw the 30 conversations across the recorded dimension")
    depth = commands.add_parser("depth", help="add one search's hits as pending suggestions")
    depth.add_argument("--input", type=Path, required=True)
    commands.add_parser("final", help="draw the last 15 uniform conversations")
    commands.add_parser("status", help="show the batches drawn so far")
    args = parser.parse_args()

    if args.command == "status":
        print(report(load_manifest()))
        return
    conversations = trace_data.load_conversations(args.source)
    if args.command == "start":
        manifest = start(conversations, args.dimension, args.source)
    elif args.command == "dimension":
        manifest = draw_dimension(conversations)
    elif args.command == "final":
        manifest = draw_final(conversations)
    else:
        manifest, added = add_depth(conversations, json.loads(args.input.read_text()))
        print(f"added {len(added)} pending suggestions")
    print(report(manifest))


if __name__ == "__main__":
    main()

"""Offline checks for the Homework 4 review interface. Nothing here reaches Langfuse."""

from __future__ import annotations

import json

import pytest

from analysis.helpers import _state, tools
from analysis.helpers.normalization import normalize_trace
from analysis.review_app import conversations, sampling, store


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("CARTWHEEL_ANALYSIS_STATE", str(tmp_path))
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


class FakeLangfuse:
    def __init__(self, fail: bool = False) -> None:
        self.scores: list[dict] = []
        self.fail = fail

    def create_score(self, **score) -> None:
        if self.fail:
            raise RuntimeError("langfuse is down")
        self.scores.append(score)

    def flush(self) -> None:
        pass


SYSTEM = {"role": "system", "parts": [{"type": "text", "content": "- User role: merchant\n- User id: 9005\n- Store id: 5"}]}


def raw_trace(trace_id, session, when, user, reply, history=(), this_turn=(), spans=(), scenario="support-0001"):
    """A trace in the shape Langfuse returns: the model's steps sit in the last generation's input."""
    question = {"role": "user", "parts": [{"type": "text", "content": user}]}
    generation = {"type": "GENERATION", "name": "openai.response", "startTime": when, "output": None,
                  "input": [SYSTEM, *history, question, *this_turn]}
    tool_spans = [{"type": "TOOL", "name": name, "startTime": when, "input": args, "output": out}
                  for name, args, out in spans]
    return normalize_trace({
        "id": trace_id,
        "timestamp": when,
        "input": [question],
        "output": [{"role": "assistant", "parts": [{"type": "text", "content": reply}]}],
        "metadata": {"attributes": {"cartwheel.session_id": session, "cartwheel.scenario_id": scenario,
                                    "cartwheel.user_role": "merchant"}},
        "observations": [generation, *tool_spans],
    })


TOOL_TURN = [
    {"role": "assistant", "parts": [
        {"type": "thinking", "thinking": "I should look it up.", "signature": "x"},
        {"type": "text", "content": "Let me check that order."},
        {"type": "tool_call", "id": "t1", "name": "get_order", "arguments": "{'order_id': 7}"},
    ]},
    {"role": "tool", "parts": [{"type": "tool_call_response", "id": "t1", "response": "{'ok': True}"}]},
]


def test_rebuild_recovers_steps_the_normalizer_drops():
    record = raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "where is it?", "It shipped.", this_turn=TOOL_TURN,
                       spans=[("get_order", {"order_id": 7}, {"ok": True, "status": "shipped"})])
    assert [m["role"] for m in record["trace"]].count("assistant") == 1

    turn = conversations.build_conversations([record])[0]["turns"][0]
    assert [step["kind"] for step in turn["steps"]] == ["thinking", "agent_text", "tool"]
    tool = turn["steps"][2]
    assert tool["arguments"] == {"order_id": 7}
    assert tool["result"] == {"ok": True, "status": "shipped"}
    assert tool["error"] is None
    assert turn["reply"] == "It shipped."


def test_a_later_turn_keeps_only_its_own_steps():
    earlier = [{"role": "user", "parts": [{"type": "text", "content": "first"}]},
               {"role": "assistant", "parts": [{"type": "text", "content": "first reply"}]}]
    record = raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "second", "second reply", history=earlier)
    assert conversations.build_conversations([record])[0]["turns"][0]["steps"] == []


def test_turns_are_grouped_by_session_in_time_order():
    records = [
        raw_trace("b" * 32, "s1", "2026-10-23T10:05:00Z", "later", "ok"),
        raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "earlier", "ok"),
        raw_trace("c" * 32, "s2", "2026-10-23T10:01:00Z", "other", "ok", scenario="support-0002"),
    ]
    built = conversations.build_conversations(records)
    assert [len(c["turns"]) for c in built] == [2, 1]
    assert [t["user"] for t in built[0]["turns"]] == ["earlier", "later"]
    assert [t["turn"] for t in built[0]["turns"]] == [1, 2]
    assert built[0]["store_id"] == "5"


def test_a_failed_tool_call_is_flagged():
    failure = {"ok": False, "error": "permission_denied", "reason": "not yours"}
    record = raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "q", "r", this_turn=TOOL_TURN,
                       spans=[("get_order", {"order_id": 7}, failure)])
    step = conversations.build_conversations([record])[0]["turns"][0]["steps"][-1]
    assert step["error"] == {"code": "permission_denied", "reason": "not yours"}


def test_pilot_traces_stay_out():
    record = raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "q", "r", scenario="pilot-01")
    assert conversations.build_conversations([record]) == []


def fake_conversations(count: int = 120) -> list[dict]:
    roles = ("shopper", "merchant", "support")
    return [
        {
            "session_id": f"s{i}",
            "scenario_id": f"support-{i:04d}",
            "role": roles[i % 3],
            "turns": [{"trace_id": f"{i:032x}", "turn": 1, "user": "q", "reply": "r", "steps": []}],
        }
        for i in range(count)
    ]


def test_batches_never_share_a_conversation_and_skip_the_preliminary_ones(state):
    population = fake_conversations() + [
        {"session_id": "prelim", "scenario_id": sampling.PRELIMINARY[0], "role": "shopper",
         "turns": [{"trace_id": "f" * 32, "turn": 1, "user": "q", "reply": "r", "steps": []}]}
    ]
    sampling.start(population, "role")
    sampling.draw_dimension(population)
    manifest = sampling.draw_final(population)

    drawn = [e["session_id"] for b in manifest["batches"] for e in b["conversations"]]
    assert len(drawn) == 75 and len(set(drawn)) == 75
    assert "prelim" not in drawn
    assert manifest["dimension"] == "role"
    spread = [e["role"] for e in sampling._batch(manifest, sampling.DIMENSION)["conversations"]]
    assert {role: spread.count(role) for role in set(spread)} == {"shopper": 10, "merchant": 10, "support": 10}
    with pytest.raises(ValueError, match="never redrawn"):
        sampling.draw_final(population)


def test_a_search_adds_new_conversations_to_the_depth_batch_only_once(state):
    population = fake_conversations()
    sampling.start(population, "role")
    already = sampling.load_manifest()["batches"][0]["conversations"][0]["trace_ids"][0]
    fresh = next(c for c in population if c["session_id"] not in sampling._sampled_sessions(sampling.load_manifest()))
    hits = [{"trace_id": already, "reason": "r"}, {"trace_id": fresh["turns"][0]["trace_id"], "reason": "r"}]
    manifest, added = sampling.add_depth(population, {"search": "s", "mode": None, "suggestions": hits})

    assert len(added) == 2 and all(s["status"] == "pending" for s in added)
    assert [e["session_id"] for e in sampling._batch(manifest, sampling.DEPTH)["conversations"]] == [fresh["session_id"]]


CONTEXT = {"trace_id": "a" * 32, "session_id": "s1", "scenario_id": "support-0001", "turn": 1}


def test_editing_a_note_keeps_the_original(state):
    store.save_annotation(CONTEXT, "the first reading")
    row = store.save_annotation(CONTEXT, "a sharper reading")
    assert row["note"] == "a sharper reading"
    assert [h["note"] for h in row["history"]] == ["the first reading"]


def test_rewriting_an_accepted_suggestions_note_makes_it_the_reviewers(state):
    store.save_annotation(CONTEXT, "the filter's wording", source="accepted_suggestion")
    row = store.save_annotation(CONTEXT, "my own reading")
    assert row["source"] == "human"
    assert [(h["note"], h["source"]) for h in row["history"]] == [("the filter's wording", "accepted_suggestion")]


def test_no_failure_counts_as_reviewed(state):
    assert store.save_annotation(CONTEXT, "No failure observed")["no_failure"] is True
    assert CONTEXT["trace_id"] in store.reviewed_traces()


def _final_mode(name: str = "reply_overclaims") -> dict:
    store.save_annotation(CONTEXT, "reply says refunded but the tool queued it")
    mode = store.save_mode({"name": name})
    store.assign_note(CONTEXT["trace_id"], mode["id"], True)
    return store.save_mode({"id": mode["id"], "status": "confirmed"})


def test_the_report_helper_reads_a_final_mode(state, tmp_path):
    from analysis.helpers import failure_report

    mode = _final_mode()
    store.save_mode({"id": mode["id"], "requirement": "RESP-2"})
    entry = failure_report(tmp_path / "report.json")["modes"][0]
    assert entry["requirement_source"] == "RESP-2"
    assert entry["examples"] == [CONTEXT["trace_id"]]
    assert store.annotations()[0]["author"] == "human"


def test_only_a_note_the_reviewer_wrote_can_support_a_mode(state):
    store.save_annotation(CONTEXT, "the filter's wording", source="accepted_suggestion")
    mode = store.save_mode({"name": "reply_overclaims"})
    with pytest.raises(store.ReviewError, match="only a note you wrote"):
        store.assign_note(CONTEXT["trace_id"], mode["id"], True)


def test_a_final_mode_needs_a_human_note(state):
    mode = store.save_mode({"name": "reply_overclaims"})
    with pytest.raises(store.ReviewError, match="supporting note"):
        store.save_mode({"id": mode["id"], "status": "confirmed"})


def test_a_proposal_must_cite_human_notes(state):
    with pytest.raises(store.ReviewError, match="must cite"):
        store.propose_mode("from_my_own_reading", "a definition", [])
    with pytest.raises(store.ReviewError, match="must cite"):
        store.propose_mode("from_my_own_reading", "a definition", ["a-unknown"])
    store.save_annotation(CONTEXT, "no failure observed")
    with pytest.raises(store.ReviewError, match="must cite"):
        store.propose_mode("from_a_clean_trace", "a definition", [CONTEXT["trace_id"]])


def test_mode_revisions_are_recorded(state):
    mode = store.save_mode({"name": "reply_overclaims", "definition": "first"})
    mode = store.save_mode({"id": mode["id"], "definition": "second"})
    assert [(r["field"], r["old"], r["new"]) for r in mode["revisions"]] == [("definition", "first", "second")]


def test_the_starters_demo_label_file_cannot_be_reused(state):
    _state.append_jsonl(_state.state_path("labels", "unsupported_policy_claim.jsonl"),
                        {"trace_id": "upc-fail-tr-00", "label": 1})
    with pytest.raises(store.ReviewError, match="demonstration"):
        store.save_mode({"name": "unsupported_policy_claim"})


def test_changing_a_judgment_replaces_the_score_and_keeps_the_history(state):
    _final_mode()
    client = FakeLangfuse()
    store.save_label(CONTEXT, "reply_overclaims", True, evidence="tool said queued", client=client)
    store.save_label(CONTEXT, "reply_overclaims", False, close_negative=True, client=client)

    assert {s["score_id"] for s in client.scores} == {f"{'a' * 32}-reply_overclaims"}
    assert [s["value"] for s in client.scores] == [1, 0]
    file_rows = _state.read_jsonl(_state.state_path("labels", "reply_overclaims.jsonl"))
    assert len(file_rows) == 2 and file_rows[0]["superseded_by"] == file_rows[1]["label_id"]
    live = tools._load_labels("reply_overclaims")
    assert len(live) == 1 and live[0]["label"] == 0 and live[0]["close_negative"] is True


def test_a_langfuse_failure_keeps_the_local_judgment(state):
    _final_mode()
    result = store.save_label(CONTEXT, "reply_overclaims", True, client=FakeLangfuse(fail=True))
    assert result["langfuse_sent"] is False and "down" in result["langfuse_error"]
    assert tools._load_labels("reply_overclaims")[0]["label"] == 1

    client = FakeLangfuse()
    assert store.resend_labels(client)["sent"] == 1
    assert tools._load_labels("reply_overclaims")[0]["langfuse_sent"] is True


def test_only_final_modes_take_judgments(state):
    store.save_mode({"name": "still_a_candidate"})
    with pytest.raises(store.ReviewError, match="not a final mode"):
        store.save_label(CONTEXT, "still_a_candidate", True, client=FakeLangfuse())


def _suggestion(mode: str) -> dict:
    other = {**CONTEXT, "trace_id": "b" * 32, "quote": "q", "reason": "looks like the mode"}
    return store.add_suggestions("search one", mode, "keyword filter", [other])[0]


def test_a_rejected_suggestion_needs_a_reason_and_stays_on_disk(state):
    _final_mode()
    suggestion = _suggestion("reply_overclaims")
    with pytest.raises(store.ReviewError, match="say why"):
        store.decide_suggestion(suggestion["id"], "rejected", "  ")
    store.decide_suggestion(suggestion["id"], "rejected", "the tool did confirm success")

    saved = store.suggestions()
    assert saved[0]["status"] == "rejected" and saved[0]["decision_reason"] == "the tool did confirm success"
    assert tools._load_labels("reply_overclaims") == []
    assert "b" * 32 in store.modes()[0]["rejected_trace_ids"]


def test_changing_a_decision_moves_the_trace_and_keeps_the_first_decision(state):
    mode = store.save_mode({"name": "still_a_candidate"})
    suggestion = _suggestion("still_a_candidate")
    store.decide_suggestion(suggestion["id"], "accepted")
    store.decide_suggestion(suggestion["id"], "rejected", "a policy question, not a dispute")

    saved = next(m for m in store.modes() if m["id"] == mode["id"])
    assert saved["positive_trace_ids"] == [] and saved["rejected_trace_ids"] == ["b" * 32]
    row = store.suggestions()[0]
    assert row["status"] == "rejected" and [h["status"] for h in row["history"]] == ["accepted"]


def test_a_suggestion_is_never_a_label_until_accepted(state):
    _final_mode()
    suggestion = _suggestion("reply_overclaims")
    assert tools._load_labels("reply_overclaims") == []
    store.decide_suggestion(suggestion["id"], "accepted", "the reply overclaims", client=FakeLangfuse())

    live = tools._load_labels("reply_overclaims")
    assert [(r["label"], r["source"]) for r in live] == [(1, "accepted_suggestion")]
    assert "b" * 32 in store.reviewed_traces()


def test_progress_reports_fractions_gaps_and_new_modes_by_batch(state):
    population = fake_conversations()
    manifest = sampling.start(population, "role")
    entry = manifest["batches"][0]["conversations"][0]
    context = {"trace_id": entry["trace_ids"][0], "session_id": entry["session_id"],
               "scenario_id": entry["scenario_id"], "turn": 1}
    store.save_annotation(context, "reply says refunded but the tool queued it")
    mode = store.save_mode({"name": "reply_overclaims"})
    store.assign_note(context["trace_id"], mode["id"], True)
    store.save_mode({"id": mode["id"], "status": "confirmed"})
    store.save_label(context, "reply_overclaims", True, client=FakeLangfuse())
    second = manifest["batches"][0]["conversations"][1]
    store.save_annotation({"trace_id": second["trace_ids"][0], "session_id": second["session_id"],
                           "scenario_id": second["scenario_id"], "turn": 1}, "no failure observed")

    report = store.progress(sampling.load_manifest())
    assert report["totals"]["traces_reviewed"] == 2
    row = report["modes"][0]
    assert (row["present"], row["fraction"], row["missing"]) == (1, 1.0, 1)
    assert [i["trace_id"] for i in report["incomplete"]] == [second["trace_ids"][0]]
    assert report["discovery"][0]["new_modes"] == ["reply_overclaims"]
    assert report["discovery"][1]["new_modes"] == []


def test_answer_keys_are_served_separately_from_conversations():
    record = raw_trace("a" * 32, "s1", "2026-10-23T10:00:00Z", "q", "r")
    built = conversations.build_conversations([record])[0]
    assert "expected" not in json.dumps(built)

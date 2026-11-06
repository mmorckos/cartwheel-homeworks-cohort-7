# HW4 report: error analysis of the Cartwheel traces

Michael Morckos · branch `hw-4` · traces from the HW3 final run (agent model `claude-haiku-4-5`) · local Langfuse

The handout's required write-ups are `analysis/report/review_summary.md`, which opens with a post for the course channel, and `analysis/report/interface_comparison.md`. This report summarizes them, with the checks behind them.

## Summary

- **Reviewed:** 107 traces in 78 conversations, drawn from the 365 traces (250 conversations) of the HW3 final run.
  - 71 notes say "no failure observed" and 36 describe a failure.
  - Each note records the first failure in its trace.
- **Interface:** my own review app under `analysis/review_app/`.
  - Generation outputs are empty in these traces, so the supplied normalizer drops 322 agent steps. The app rebuilds them in model order and groups turns into conversations.
- **Taxonomy:** six final binary modes, each with a definition, a boundary, an evaluator type and a requirement source. Two more were held back with fewer than three positives.
- **Labels:** every final mode judged on every reviewed trace, 642 judgments in all.
  - They are saved as Langfuse scores and in `analysis/state/labels/`, and the two match on all 642.
  - 28 traces have a mode, and none has more than one.
- **Main finding:** the agent escalates too much and too little. It opens or offers tickets for requests that policy already resolves, and elsewhere skips the ticket ESC-3 requires for a dispute.
- **Stability:** the final uniform batch (16 traces) produced 0 new modes.
- **Searches:** 13 suggestions from four filter searches: 5 accepted and 8 rejected.
- **`SPEC.md`:** RESP-6, RESP-7 and ESC-5 added, and TOOL-8 revised. The prompt and tools are unchanged, so the running agent doesn't follow them yet.
- **Live calls:**
  - No model was called in HW4, and the agent wasn't run. Sampling, clustering and searches are code over the saved traces.
  - The only live service was the local Langfuse: traces were read from it and scores written to it.
  - Claude Code, the coding agent, built the interface, proposed groupings from my notes, wrote the search filters and drafted the reports.

## 1. Part A: the review interface

**Langfuse friction.** I read 9 traces from 7 conversations in the annotation queue `hw4-preliminary`, chosen by role, turn count and tools, not by outcome:
- Tool results are a few steps away from the reply that describes them.
- The policy text isn't always visible.
- Earlier turns and context are hard to see.
- Comments attach to individual spans, not to the whole trace.

**Kept from the reference interface:**
- a standard-library Python server over JSON files in `analysis/state/`;
- one self-contained HTML page;
- a color per role, and one container for a tool call and its result.

**Changed after inspecting the traces:**
- **The problem:** generation outputs are empty on all 697 generations, so the normalizer keeps only each turn's final reply. It drops 322 agent text steps and 257 thinking blocks, and agent text steps occur in 250 of the 365 traces.
- **The rebuild:** the app rebuilds each turn from the last generation's input, in model order. All 387 tool calls match the tool spans.
- **Grouping:** turns are grouped by `cartwheel.session_id`.
- **Marking:** agent steps are tagged as not shown to the user.
- **Notes:** each turn has its own note box beside it.

**Also built for this review:**
- the answer key, hidden until a button reveals it;
- a Labels view with "Absent for the rest";
- a stable Langfuse score id per trace and mode, so re-saving a label replaces its score instead of adding one;
- rejected suggestions kept on disk with their reasons;
- a history for every note, decision and mode revision;
- a Progress view with "Compare with Langfuse".

**Remaining limitations:**
- Open codes stay in `analysis/state/annotations.json`.
- The interface can't look up arbitrary records, because `data/cartwheel.db` changed during the run.
- The thinking behind each final reply isn't in the traces.

The server runs on port 8022, because macOS `launchd` holds 8021.

## 2. Part B: the review

| Batch | Method | Target | Coded |
| --- | --- | --- | --- |
| `uniform_start` | Uniform over conversations | 15 | 15 conversations, 21 traces |
| `cluster_representatives` | k-means on structure (k=8), nearest each centroid | 15 | 15 conversations, 23 traces |
| `dimension` | Even spread across `role`, chosen before drawing | 30 | 30 conversations, 38 traces |
| `depth_search` | Search hits for candidate modes and close negatives | 25 | 8 conversations, 9 traces |
| `uniform_final` | Uniform, after the taxonomy draft | 15 | 10 conversations, 16 of 21 traces |
| **Total** | | **100** | **78 conversations, 107 traces** |

| Role | Conversations | Traces | Failure notes |
| --- | --- | --- | --- |
| shopper | 43 | 63 | 21 |
| merchant | 18 | 21 | 5 |
| support | 17 | 23 | 10 |

- **Draws:** batches draw conversations, and every turn gets its own note. Seeds and reasons are in `analysis/state/sample_manifest.json`.
- **Authorship:**
  - I wrote 100 of the 107 notes.
  - 3 use the wording of a search suggestion I accepted (0137, 0210, 0212).
  - Claude drafted 4 after I chose what each says (0024, 0143, 0160, 0241). They're marked `claude_draft`, with the earlier text in `history`.
- **Uncoded:** the five uncoded final-batch traces are 0178, 0218, 0219, 0225 and 0228. Three are merchant conversations, so the coded part of that batch leans toward shoppers.

## 3. Part D: the failure modes

| Mode | Present when | Present | Close negatives | Sample fraction | Requirement | Evaluator |
| --- | --- | --- | --- | --- | --- | --- |
| `unneeded_escalation` | The agent calls `escalate_to_human`, or offers to, for a request policy and the order record resolve, and no SPEC §5 case applies | 10 | 3 | 9.3% | ESC-5 (new) | LLM judge |
| `asks_for_unusable_information` | The reply asks for information no tool accepts and that wouldn't change the next step | 5 | 3 | 4.7% | RESP-6 (new) | LLM judge |
| `inconsistent_record_not_escalated` | A retrieved order record contradicts itself and the turn ends without a successful escalation | 4 | 1 | 3.7% | ESC-3, RESP-3 | code |
| `asks_for_cancel_reason` | A cancel request gets a question about the reason instead of a check or a cancellation | 3 | 3 | 2.8% | TOOL-8 (revised) | LLM judge |
| `assumes_order_without_confirming` | Several orders match and the reply treats one as the user's without asking which | 3 | 3 | 2.8% | RESP-7 (new) | LLM judge |
| `required_escalation_not_made` | The user raises a dispute or a request the agent can't resolve, and the turn ends with no ticket, including when the agent asks permission first | 3 | 3 | 2.8% | ESC-3 | LLM judge |

- **Sample fractions, not prevalence:** clustering and searches shaped the sample on purpose.
- **Where the details are:** full definitions, boundaries, likely fixes and supporting traces are in `analysis/state/patterns.json` and the review summary.
- **Close negatives:** `inconsistent_record_not_escalated` has only one, because no reviewed trace shows an inconsistent order record that the agent escalated.
- **Not final:**
  - `refund_promised_without_tool` (RESP-2) has 1 positive.
  - `reply_omits_order_details` has 2.
- **Failure notes in no mode:** replies longer than the user wanted (0122 t3, 0162), a misstatement of who handles disputes (0143), and a request for a store name the session already holds (0199). 0196 and 0106 are close negatives.

## 4. The escalation boundary: two modes, one revision, one rejected suggestion

**`unneeded_escalation` (0103).**
- The user wants to get rid of a delivered order. `check_return_eligibility` returns `window_passed`, the user raises no dispute, and the agent opens a ticket anyway.
- The rebuilt trace shows a step the user never sees: there, the agent explains that the window closed and cites `cw-returns`. The reply only says a ticket was opened.

**`required_escalation_not_made` (0135).**
- The user writes "I'd like to dispute the charge." The only tool call is `find_order`.
- The reply ends with "Would you like me to escalate this now?", and no ticket is opened.

**They stay separate** because the fixes are opposite: one stops needless tickets, and the other opens the ticket immediately.

**The revision.**
- `unneeded_escalation` first covered only a call to `escalate_to_human`, based on 0103.
- In the role batch, my notes on 0040 and 0060 described an offer to escalate with no ticket. One product change fixes all three, so the definition became "calls, or offers to".
- That overlapped 0135, which also shows an offer. The boundary is now whether the user raised a dispute or a request the agent can't resolve.
- The earlier text is kept in the mode's `revisions`.

**The rejected suggestion (0132).**
- The search "ticket opened after `window_passed`" matched 0132 exactly, with the same tool sequence as 0103.
- The user writes "dispute charge" and says the item was damaged. I rejected it: "The user raised a dispute, so ESC-3 requires the ticket."
- 0132 is a close negative for both modes.

## 5. Search for additional instances

Four searches used filters over the trace data, with no model. A hit is a retrieval signal, not a label.

| Search | Accepted | Rejected | Boundary for the rejections |
| --- | --- | --- | --- |
| `unneeded_escalation`, first definition (ticket on a closed window) | 0212 | 0132, 0134, 0136 | The user raised a dispute, so ESC-3 requires the ticket |
| `unneeded_escalation`, widened definition (offer on a closed window) | 0077, 0210 | 0137 | The user raised a dispute, so it belongs to `required_escalation_not_made` |
| `assumes_order_without_confirming` | 0044 | 0024, 0065 | The reply asks which order the user means |
| `required_escalation_not_made` | 0131 | 0143, 0160 | A policy question, not a raised dispute |

I first accepted 0024, 0137, 0143 and 0160, then rejected them after comparing them with the definitions. The first decisions are kept in each suggestion's `history`.

## 6. `SPEC.md` revisions

| Change | Text | Motivating notes |
| --- | --- | --- |
| New RESP-6 | Ask the user only for information a tool accepts or that decides the next step. | 0011 t1, 0030 t2 |
| New RESP-7 | When more than one order matches the user's description, list them and ask which one before acting on or reporting about one. | 0023 t1, 0067 t1 |
| New ESC-5 | Do not escalate, or offer to escalate, a request that policy and the order record resolve and that no case above covers. State the decision and cite the policy. | 0040 t1, 0060 t1, 0103 t1 |
| Revised TOOL-8 | The agent takes the cancellation reason from the user's request and does not ask for it separately. | 0108 t1, 0109 t1 |

Before ESC-5, the spec said when to escalate but not when not to, so `unneeded_escalation` had no requirement. Before the TOOL-8 change, the spec listed `reason` as an input, so asking for one didn't clearly break it.

## 7. Comparison with AgentDebug

Source: Zhu et al., "Where LLM Agents Fail and How They can Learn From Failures" ([arXiv:2509.25370](https://arxiv.org/abs/2509.25370)). Its AgentErrorTaxonomy has 17 types across memory, reflection, planning, action and system.

- **Retrieval Failure** is the closest gap. Two notes describe a missed lookup (0109, 0143), which is too few for a mode, so I added none.
- **Parameter Error:** in 0199 the agent passed `store: '1'` to `search_products`, which takes a store name. That's one note.
- **System errors:**
  - 13 of the 365 traces contain a failed tool result, and 7 of those are in the review set.
  - All are `not_found` or `not_eligible`, which SPEC section 4 treats as expected results, not malfunctions.

## 8. Checks

| Check | Kind | Result |
| --- | --- | --- |
| Langfuse read of every trace | Live service, read-only, no model | Rebuilt the same 250 conversations and 365 traces as the export, identical on all 250 |
| Compare with Langfuse (Progress view) | Live service, read-only | 642 match, 0 differ (run by me and by Claude) |
| Interface views in Chrome | Offline, read-only or on a temporary state copy | Labels rail, Taxonomy and the rebuilt 0103 render as saved |
| `uv run pytest tests/test_review_app.py tests/test_hw_holes.py -q`, before the final fix | Offline | 1 failed, 41 passed, 2 skipped, 7 xfailed, 9 xpassed |
| The same tests after the commit | Offline | pytest's cache records a run that collected all 24 interface tests and left only `test_m2_failure_report_matches_artifact_l_schema` as failing. That run's counts and error text weren't captured |

**The failing course test.**
- **The first failure** ("origins must be human annotations") was a bug in the interface. It saved a mode's originating notes in a different format from the course's, and one origin (0137) used a filter's wording. Note ids are now trace ids, and 0137 is listed as a positive. No note, judgment or label changed.
- **The remaining failure:** Claude checked offline, on a copy of the state, that all six modes pass the test's schema, example and human-origin checks. The test then looks up the course's demo mode, `unsupported_policy_claim`, which this taxonomy doesn't contain, and stops on `StopIteration`.
- **Unconfirmed:** that `StopIteration` is the error in my own run.
- **Left as is:** the test and the taxonomy are unchanged.

## 9. Notes

- **Limits:**
  - The depth batch has 9 traces against a target of 25.
  - `asks_for_cancel_reason` and `inconsistent_record_not_escalated` each rest on two conversations, and both `inconsistent_record_not_escalated` conversations concern order 8001.
  - Part C (Raindrop Workshop) is optional and was skipped.
- **Label provenance:**
  - I made 595 of the 642 judgments in the Labels view.
  - 47 are marked `reviewer_decision`: 40 recorded by Claude from decisions I had already made in notes and suggestion reviews, and 7 close-negative tags I approved.
- **Label files are append-only:** they hold 680 rows. The latest row per trace and mode gives the 642 judgments.
- **For HW5:** it needs 30 Pass and 30 Fail labels per mode. The largest mode has 10 Present, so the handout's synthetic scenarios will be needed.
- **Video:** recorded.

## Reproduce

```bash
docker compose -f observability/docker-compose.yml up -d
uv run python -m analysis.review_app.server          # http://127.0.0.1:8022
uv run pytest tests/test_review_app.py tests/test_hw_holes.py -q
```

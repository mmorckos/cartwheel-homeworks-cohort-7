# HW3 report: synthetic scenarios and the traced final run

Michael Morckos · branch `hw-3` · agent model `claude-haiku-4-5` · message writer `claude-sonnet-5-5` · local Langfuse

## Summary

- **Dimensions:** seven, plus the turn count: role, intent, record state, applicable policy, tools needed, difficulty, and user style. They were approved before any generation.
- **Pilot:**
  - 30 scenarios, all 30 completed.
  - 12 reviewed: **9 confirmed failures**, and 3 invalid scenarios (20, 21, 22) recorded as not failures.
  - The invalid ones were carried into the final set as fixed patterns, not as copies.
- **Final set:**
  - 250 scenarios: 175 coverage and 75 challenge, with 5 per damaged record. Ids are `support-0001`…`support-0250`.
  - `--final` validation passes.
  - 15 reviewed, all accepted. 50 monitoring scenarios selected.
- **Final run:**
  - **250/250 completed**: coverage 175, challenge 75.
  - 365 traces, exported for all 250 ids.
  - Three exported traces checked: 0250 (multi-turn), 0183 (challenge) and 0070 (coverage). Each had the conversation, the model, tool activity and `cartwheel_scenario_id`.
- **Live calls:**
  - Sonnet wrote and critiqued the user messages.
  - Haiku ran the agent: 30 pilot scenarios and 250 final ones.
  - Everything else (plan building, validation, repetition checks, selection, and the export count) ran offline.

## 1. How the scenarios were built

- **Plans come from the data, not the model.**
  - The pilot plan (`pilot_plan.py`) was written by hand from read-only queries.
  - The final plan comes from a builder (`support_plan.py`). It seeds a fresh world in a temporary folder, so its records match what `seed.generate` restores before the run.
  - Expected outcomes come from four sources: SQL, `seed.eligibility.is_refund_eligible` and `refund_needs_approval`, the policy documents, and the `data_quality_cases` table.
- **Builder checks** (offline):
  - No order is used by two scenarios.
  - Every shopper appears in one scenario only. The exceptions are the owners of the damaged orders (119, 174 and 392).
  - No pilot order is reused.
  - Every stamped `refund_eligible` flag agrees with `is_refund_eligible`.
- **Messages:**
  - One Sonnet call writes each conversation from a brief that holds only what the user knows. An independent critic call then repairs it. Neither call sees `expected`.
  - Two repetition passes follow:
    - An opening pass allows at most 2 conversations per 3-word opening.
    - A phrase pass keeps a 5-word phrase that appears in 6 or more conversations in the first 3 and rewrites the rest. It also rewrites near-copies of earlier openings.
  - Final file: the critic fixed 45 conversations. 63 had their opening reworded, and 39 had repeated phrases reworded.
- **Repetition before and after the phrase pass:**
  - The 5-word phrases appearing in 6 or more messages went from 7 to 0. "I don't have the order number" appeared 16 times before the pass.
  - Near-identical opening pairs went from 4 to 0.
  - No opening's first 3 words repeat more than twice.
  - No message names a policy id, rule number or tool.

## 2. Pilot (30 scenarios, 3.1 min of agent time)

| Scenario | Valid | Failure | Evidence |
| --- | --- | --- | --- |
| 07 | yes | yes | Order 546 had shipped (cw-cancellations); no tool call, and the agent promised "I'll process it right away" |
| 10 | yes | yes | Address change; no `escalate_to_human` (ESC-2) |
| 12 | yes | yes | Said "I'm going to escalate", but no ticket was opened (RESP-2, cw-disputes) |
| 14 | yes | yes | "No access to payout schedules"; never searched; `cw-payouts` answers it |
| 19 | yes | yes | Promised a refund on order 8003 (`inconsistent_record`, 84 days past delivery); named only "the data issue" (RESP-3) |
| 26 | yes | yes | $177.25: no `issue_refund` call, so no refund was queued; escalated instead (ESC-1) |
| 29 | yes | yes | 32 orders in SQL; the agent said "20 orders" (RESP-3) |
| 30 | yes | yes | Took order 10000 (a ceramics store) for the keyboard; the keyboard was order 22, past its window |
| 01 | yes | yes | Offered a refund for a lost package without checking eligibility (ESC-4) |
| 20 | no | no | The reason listed 2 "Heavy-Duty Vase" listings; there are 4 |
| 21 | no | no | No tool lists a store's whole catalog, so "three cheapest items" can't be answered |
| 22 | no | no | No order tool returns product titles, so the empty title can't surface |

**How the three invalid scenarios became final patterns:**
- **Invalid price:** cheapest-pitcher searches, where the −$5 listing sorts first.
- **Missing title:** portable-tray searches, which return product 3 with an empty title.
- **Duplicate title:** each vase reason lists every matching listing, read from the data.

## 3. Final dataset

| Group | Shopper | Merchant | Support | Multi-turn | Total |
| --- | --- | --- | --- | --- | --- |
| coverage | 98 | 43 | 34 | 44 | 175 |
| challenge | 44 | 15 | 16 | 20 | 75 |

- **Coverage:**
  - All 10 intents, weighted toward orders, returns, refunds and policy questions.
  - Difficulty: 125 well specified, 28 missing information, 22 ambiguous.
  - All 8 styles, about 22 each.
- **Challenge:**
  - 30 damaged records (6 cases × 5).
  - 8 return-window boundaries (last day, and one day past).
  - 6 refund-threshold cases, including partial refunds of exactly $100.00 and $100.50.
  - 8 store overrides and restocking fees.
  - 7 authorization edges, 6 corrections across turns, and 6 incomplete lists and look-alikes.
  - 4 conversations of sustained pressure, 4–6 turns each.
- **Review:**
  - 15 reviewed: both groups, all roles, every intent and all 8 styles. All accepted.
  - The sample included the longest conversation (0250, 6 turns), two requests that change data (0206 and 0100), and three conversations the phrase pass had rewritten.
  - No scenario was revised or replaced after review.
- **Monitoring:**
  - 50 scenarios: 35 coverage, chosen in proportion to intent, and 15 challenge, one of each challenge kind.
  - Roles: 25 shoppers, 13 merchants, 12 support.

## 4. Final run and traces

The data was reset with `uv run python -m seed.generate` before the run. The run took 27.4 minutes of agent time.

| Group | Completed | Traces | Tool calls | Permission denials | Turns with no tool call |
| --- | --- | --- | --- | --- | --- |
| coverage | 175/175 | 259 | 264 | 0 | 83 |
| challenge | 75/75 | 106 | 123 | 4 | 25 |

- **Tool calls in the challenge group:**
  - `escalate_to_human` 18 times, against 7 in coverage.
  - `issue_refund` once, against 10 in coverage.
  - These figures describe what ran, not how well the agent did. Judging the results starts in HW4.
- **Smoke report** (`reports/smoke-output.txt`). Its counts cover every trace in Langfuse, including the pilot and HW2:
  - **Roles:** 253 shopper, 89 merchant and 71 support traces.
  - **Tools:** 106 calls to `check_return_eligibility` and 97 to `get_order`.
  - **Escalations and denials:** 31 escalations and 6 permission denials.
  - **Errors:** no ERROR-level observations.
  - **Tokens and cost:** tokens were 0 and cost NULL. Usage isn't captured on the `claude-haiku-4-5` generation spans, so this does not mean the calls were free.
- **Export** (`traces/support_traces.json`): 365 traces for 250 of 250 ids, with no missing ids. There are 697 generation spans, all `anthropic/claude-haiku-4-5`. The file is 10.6 MB and contains no credential patterns.

## 5. Notes

- **Seven pairs of short, generic followups remain similar.** One example is "What do I tell the customer?". They're everyday phrasing and were left as they are.
- **Scenarios that refund or cancel assume freshly seeded data.** Rerunning them, including the monitoring set in HW7, needs `seed.generate` first.
- **Pending:** the video.

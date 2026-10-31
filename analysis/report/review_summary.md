# Review summary

Claude drafted this from the saved state files for the reviewer to check before submission. No model was called to produce it.

## Size of the review

The review covers 107 distinct traces in 78 conversations, above the required 100.

| Batch | Handout target (traces) | Conversations coded | Traces coded | Status |
| --- | --- | --- | --- | --- |
| `uniform_start` | 15 | 15 of 15 | 21 | Complete |
| `cluster_representatives` | 15 | 15 of 15 | 23 | Complete |
| `dimension` (role) | 30 | 30 of 30 | 38 | Complete |
| `depth_search` | 25 | 8 of 8 | 9 | Complete, but 16 under its target |
| `uniform_final` | 15 | 10 of 15 | 16 of 21 | Target met; 5 drawn traces not coded |
| **Total** | **100** | **78 of 83** | **107 of 112** | |

Batches were drawn as conversations, and every turn of a coded conversation has its own note, so the first three batches exceed their trace targets. The five uncoded conversations in `uniform_final` are support-0178, support-0218, support-0219, support-0225, and support-0228. Three of them are merchant conversations, so the coded part of that batch leans toward shoppers. They have no notes or labels and are not part of the review set. Part C (Raindrop Workshop) is optional and was skipped.

## Composition of the reviewed sample

| Role | Conversations | Traces | Failure notes |
| --- | --- | --- | --- |
| shopper | 43 | 63 | 21 |
| merchant | 18 | 21 | 5 |
| support | 17 | 23 | 10 |
| **Total** | **78** | **107** | **36** |

The other 71 notes say "no failure observed". These counts describe a sample shaped by the selection methods, so they are not prevalence estimates.

Of the 107 notes, the reviewer wrote 100. Three use the wording of a search suggestion the reviewer accepted (support-0137, support-0210, support-0212). Claude wrote four at the reviewer's request after the reviewer chose what each should say (support-0024, support-0143, support-0160, support-0241). Those four are marked `claude_draft`, and their earlier text is kept in `history`.

## Failure modes

Claude proposed these groups from the reviewer's notes, and the reviewer chose which to keep and which to make final.

| Mode | Status | Supporting traces (scenario, turn) | Requirement source |
| --- | --- | --- | --- |
| `asks_for_unusable_information` | Final | 0011 t1, 0030 t2, 0045 t2, 0064 t1, 0101 t1 | RESP-6 (new) |
| `asks_for_cancel_reason` | Final | 0108 t1, 0108 t2, 0109 t1 | TOOL-8 (revised) |
| `unneeded_escalation` | Final | 0040 t1, 0060 t1, 0077 t1, 0077 t2, 0103 t1, 0210 t1, 0212 t1, 0247 t1, 0247 t2, 0247 t3 | ESC-5 (new) |
| `assumes_order_without_confirming` | Final | 0023 t1, 0044 t1, 0067 t1 | RESP-7 (new) |
| `required_escalation_not_made` | Final | 0131 t1, 0135 t1, 0137 t1 | ESC-3 |
| `inconsistent_record_not_escalated` | Final | 0176 t1, 0176 t2, 0180 t1, 0180 t2 | ESC-3, RESP-3 |
| `refund_promised_without_tool` | Candidate | 0099 t1 | RESP-2 |
| `reply_omits_order_details` | Proposed | 0090 t1, 0134 t1 | None yet |

The last two have fewer than the required three positives, so they were not made final. `asks_for_cancel_reason` and `inconsistent_record_not_escalated` have enough traces but only two conversations each, and both `inconsistent_record_not_escalated` conversations concern order 8001. Definitions, boundaries, and likely fixes are in `analysis/state/patterns.json`.

These failure notes are in no mode:

- **support-0122 t3 and support-0162 t1:** replies longer than the user wanted. They share a theme, but two notes are too few for a mode.
- **support-0143 t1:** the reply misstates who handles disputes, against `cw-disputes`.
- **support-0199 t1:** asked for a store name when the session already holds the store id.
- **support-0196 t1:** the reviewer noted during labeling that the agent should have escalated a negative price. The bad value is in a product record, so it is a close negative for `inconsistent_record_not_escalated`, which covers order records.
- **support-0106 t1:** the reviewer's note says the agent assumed the order. The reply also asks which order the user means, so the reviewer treats it as a close negative for `assumes_order_without_confirming`, and the original note is kept.

## Sample fractions

All judgments are saved as Langfuse scores and in `analysis/state/labels/`. Every final mode has a judgment on each of the 107 reviewed traces, 642 in all. These are fractions of this sample, which clustering and focused searches shaped on purpose, so they are not prevalence estimates.

| Mode | Present | Absent | Close negatives | Sample fraction |
| --- | --- | --- | --- | --- |
| `unneeded_escalation` | 10 | 97 | 3 | 9.3% |
| `asks_for_unusable_information` | 5 | 102 | 3 | 4.7% |
| `inconsistent_record_not_escalated` | 4 | 103 | 1 | 3.7% |
| `asks_for_cancel_reason` | 3 | 104 | 3 | 2.8% |
| `assumes_order_without_confirming` | 3 | 104 | 3 | 2.8% |
| `required_escalation_not_made` | 3 | 104 | 3 | 2.8% |

28 of the 107 traces (26.2%) have a final mode, and none has more than one. Close negatives count among the Absent judgments.

Claude recorded 40 labels from decisions the reviewer had already made in notes and suggestion reviews: 28 Present, 9 close negatives, and 3 Absent. The reviewer made the other 602 in the Labels view, then approved close-negative tags on 7 of those Absent judgments, which Claude recorded. Those 47 are marked `reviewer_decision` in `analysis/state/labels/`.

`inconsistent_record_not_escalated` has only one close negative, because no reviewed trace shows an inconsistent order record that the agent escalated.

Comparing the local labels with Langfuse gives 642 matches and 0 differences.

## Stability

The 16 coded traces in the final batch produced 0 previously unseen consequential modes. Their failure notes fit `unneeded_escalation` (support-0247), a close negative of `assumes_order_without_confirming` (support-0106), or a theme already seen in an earlier batch (support-0122). The reviewer first noted support-0241 as a failure, "Total orders is 22 not 20", then decided it was not one, because the reply says the list may not be the full total. That original note is kept in `history`.

## Taxonomy revision

`unneeded_escalation` first covered only a call to `escalate_to_human`, based on support-0103. The notes on support-0040 and support-0060 describe an offer to escalate with no ticket, and one product change would fix all three, so the definition was widened to "calls escalate_to_human, or offers to". The widened definition overlaps `required_escalation_not_made`, because support-0135 also shows an offer. The boundary now depends on whether the user raised a dispute or a request the agent cannot resolve. The earlier text is kept in the mode's `revisions`.

## SPEC revisions

The reviewer chose all four and they are applied in `SPEC.md`. They record intended behavior only: the prompt and tools are unchanged, so the running agent does not follow them yet.

| Change | Text | Motivating notes |
| --- | --- | --- |
| New RESP-6 | Ask the user only for information a tool accepts or that decides the next step. | support-0011 t1, support-0030 t2 |
| New RESP-7 | When more than one order matches the user's description, list them and ask which one before acting on or reporting about one. | support-0023 t1, support-0067 t1 |
| New ESC-5 | Do not escalate, or offer to escalate, a request that policy and the order record resolve and that no case above covers. State the decision and cite the policy. | support-0040 t1, support-0060 t1, support-0103 t1 |
| Change to TOOL-8 | The agent takes the cancellation reason from the user's request and does not ask for it separately. | support-0108 t1, support-0109 t1 |

TOOL-8 lists `reason` as an input, so before this change asking for one did not clearly violate `SPEC.md`.

## Comparison with AgentDebug

Draft for the reviewer to check. Source: Zhu et al., "Where LLM Agents Fail and How They can Learn From Failures" ([arXiv:2509.25370](https://arxiv.org/abs/2509.25370)). Its AgentErrorTaxonomy has 17 error types across five modules: memory, reflection, planning, action, and system.

- **Possible omission:** Retrieval Failure, "Relevant info exists but is not retrieved when needed." The note on support-0109 says the agent should have said the order had shipped, and that turn has no tool call. The note on support-0143 says the agent did not search the help center. No mode covers a missing lookup. Two notes do not support adding one, so the reviewer decided not to add one.
- **Parameter Error:** "Generates unreasonable or malformed parameters." In support-0199 the agent passed `store: '1'` to `search_products`, which takes a store name, and the tool returned `not_found`. It is one note, so no mode was added.
- **System module:** no mode was added. 13 of the 365 traces contain a failed tool result, and 7 of those are in the review set. Their codes are `not_found` and `not_eligible`, which SPEC section 4 treats as expected failures rather than tool malfunctions.

## Search for additional instances

Four searches ran, using filters over the trace data and no model. A hit is a retrieval signal, not a label. The search for `unneeded_escalation` was repeated after its definition was widened.

| Search | Accepted | Rejected |
| --- | --- | --- |
| `unneeded_escalation`, first definition (ticket on a closed window) | 0212 | 0132, 0134, 0136 |
| `unneeded_escalation`, widened definition (offer on a closed window) | 0077, 0210 | 0137 |
| `assumes_order_without_confirming` | 0044 | 0024, 0065 |
| `required_escalation_not_made` | 0131 | 0143, 0160 |

That is 5 accepted and 8 rejected. The boundaries applied:

- **0132, 0134, 0136:** "The user raised a dispute, so ESC-3 requires the ticket."
- **0137:** "The user raised a dispute, so this belongs to required_escalation_not_made."
- **0024, 0065:** "The reply asks which order the user means."
- **0143, 0160:** "A policy question, not a raised dispute, so ESC-3 does not apply."

Claude drafted these reasons from the reviewer's notes and the mode definitions, and the reviewer chose them. The reviewer first accepted 0024, 0137, 0143, and 0160, then rejected them after comparing them with the definitions. Those first decisions are kept in each suggestion's `history`. support-0044 was accepted although its original note says "no failure observed"; that note is kept because the mode did not exist when it was written.

## Known test failure

`test_m2_failure_report_matches_artifact_l_schema` in `tests/test_hw_holes.py` skipped while `patterns.json` was empty. With the final modes saved, all six pass its schema, example, and human-origin checks, and it then fails because it requires the course's demo mode, `unsupported_policy_claim`, in `patterns.json`. This taxonomy does not contain that mode, which has no supporting notes from this review, so the test and the taxonomy are unchanged.

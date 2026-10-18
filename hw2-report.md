# HW2 report: the authenticated, traced Cartwheel endpoint

Michael Morckos · branch `hw-2` (commit `bfe01e7`) · agent model `claude-haiku-4-5` · local Langfuse

## Summary

- `POST /sessions` binds a database-verified identity to a server-side session and a signed token. `POST /sessions/{id}/messages` authorizes the token, then runs the agent inside a root span, `cartwheel.session_message`.
- Every tool span carries the caller (`cartwheel.user_role`, `cartwheel.user_id`, and `cartwheel.store_id` for merchants) and the permission decision, alongside OpenLLMetry's `gen_ai.*` fields.
- **9 live requests** (7 from `hw1-session.jsonl` and 2 for the prompt comparison). All completed, each as one 6-span trace. The single denial (E2) is recorded as `permission_denied=true` with its reason.
- **A two-line prompt edit** changed the version (`aaa40c2265cf` → `43b0916f1744`) and the tool calling: no tool before the edit, `escalate_to_human` after.
- **Offline checks:** the focused test, 2 authentication tests, and the full suite. **Live checks** (Haiku): the 9 traced requests.

## 1. Implementation

| Part | Function | Behavior |
| --- | --- | --- |
| A | `record_tool_result`, `_set_permission_denied_attributes` (`observability/instrument.py`) | Writes onto the active tool span: role, plus `user_id` and `store_id` as strings (store for merchants only). `permission_denied` is always a Boolean, and the reason is set only on a denial. Odd input never raises. |
| B | `create_session` (`server/app.py`) | An unknown role gives 400, an unknown user 404, and a role mismatch 403. Builds the `AuthContext` from the database row. Signs `{session_id, user_id, role, store_id, issued_at}` with HMAC and stores the context and `SQLiteSession` in `_SESSIONS`. |
| C | `post_message` (`server/app.py`) | Authorizes first (401/403/404), before any agent work. The root span records `session_id`, `user_role`, `user_id`, `prompt_version`, `scenario_id` (only if nonempty), and `gen_ai.input/output.messages`. Returns `session_id`, `reply`, and `prompt_version`. |

**How identity is established.** The client sends only `user_id` and `role`. The server verifies both against the `users` table, so a merchant's store comes from the database, never from the request. The token is bound to one session, and `_authorize` checks its signature and that its session matches the URL. The tools receive the `AuthContext` the server stored, so nothing typed in the conversation can change who the caller is.

**Compared with `hw2-reference.patch`** (a sanity check; the patch was not applied). Parts A and B match its logic. Part C differs in three deliberate ways:

- It reads the content flag with OpenLLMetry's own `should_send_prompts()`. The patch's `== "true"` test disagrees with the model spans for `1`, `yes`, and `on`.
- It has no `is_recording()` guards, because `set_attribute` on a non-recording span already does nothing.
- A small helper builds the GenAI message JSON.

It also adds `cartwheel.session_id`, which the docstring asks for and Module 2's normalization reads.

## 2. Tests (offline)

| Command | Result |
| --- | --- |
| `pytest --runxfail tests/test_hw_holes.py -k hw2` | 1 passed |
| `pytest tests/test_observability.py` | 2 passed |
| `pytest` | 1 failed, 161 passed; `LITELLM_MODE=PRODUCTION pytest`: 0 failed |

- **The two authentication tests:**
  - A role mismatch returns 403 and creates no session.
  - Shopper 1's valid token, used on shopper 2's session, returns 403 before the agent runs.

  Both use FastAPI's `TestClient` without the startup hook (so no tracing), a seeded temporary database, and a temporary sessions database. They need no Docker, no Langfuse, and no model key.
- **The full-suite failure is not HW2 code.** Importing LiteLLM loads `.env` (`litellm/__init__.py:26`), which puts the `LANGFUSE_*` values into the test process. A Module 2 test then tries to reach the live Langfuse and fails. The suite was left unchanged.

## 3. Traces (live, prompt `aaa40c2265cf`)

| # | User | Request (HW1 record) | Tool | Denied | Outcome |
| --- | --- | --- | --- | --- | --- |
| E1 | shopper 1 | status of order 4127 (1) | `get_order` | false | Delivered, with its dates and total |
| E2 | merchant 9002 | order 4127 (4) | `get_order` | **true** | "it doesn't belong to your store" |
| E3 | shopper 1 | how many orders (12) | `list_my_orders` | false | "20 orders". HW1 B11 found 26: the list is capped and gives no truncation signal. |
| E4 | shopper 1 | cheapest pitcher (13) | `search_products` | false | Flagged −$5.00 as a data error, so the HW1 RESP-3 fix held |
| E5 | shopper 333 | return order 569 (5) | `check_return_eligibility` | false | Window passed (14-day store override, last day June 20). The first live use of the HW1 tool. |
| E6 | shopper 1 | return my vase (11) | `find_order` | false | Listed the vase orders and asked which one |
| E7 | support 9501 | cancel order 10 (15) | `cancel_order` | false | Cancelled; the data was reset afterwards |

- **Every trace has 6 spans under one trace ID:** root → `Agent Workflow` → agent → model call → tool → model call. `Agent Workflow` groups the run; it is not a model call.
- **Model spans are named `openai.response`**, the SDK's name, but they record `gen_ai.request.model = anthropic/claude-haiku-4-5`.
- **`scenario_id` is absent from every trace.** Manual requests send none.
- **Langfuse stores attribute values as strings**, so the Boolean shows as `"true"` or `"false"`.

## 4. Prompt version comparison (Part F)

**Setup:** shopper 1, "Can you change the email address on my Cartwheel account to new@example.com?" (HW1 records 7–8). Both runs used a new session, the model pinned in the request body, and data reset before each run.

**The edit:** two temporary lines under `## Escalation`: "Account changes of any kind always go to a human: you cannot make them yourself, so call escalate_to_human without waiting to be asked." The rule (ESC-2) is in SPEC §5 and `cw-escalations` but was missing from the prompt.

| Run | `prompt_version` | Tool spans | Reply |
| --- | --- | --- | --- |
| F1 | `aaa40c2265cf` | none | "I can't help with account credential changes like email addresses", then points to settings |
| F3 | `43b0916f1744` | `escalate_to_human` (ticket #151, 24 h) | Escalated without being asked; the 24 hours came from the tool result |

- **The version is a hash of the exact template text**, taken before the user fields are filled in. The same two lines without their surrounding blank lines hash to `8942169e9135`.
- **The prompt was restored afterwards** with `git restore`.
- **This departs from the handout,** which prescribes reverting to the HW1 prompt (`d108f6949e5e`) when HW1 produced a revision. I used a new edit to show a change in tool calling. The required hash difference holds.

## 5. Trace record and environment

- **`hw2-traces.json`:** E2 (`8d9be5a8…`, merchant 9002, `get_order`, denied) and F3 (`d0221106…`, shopper 1, `escalate_to_human`). Both `completed`. The values were read from the Langfuse API.
- **MinIO setup issue:** MinIO (Langfuse's blob store) crashed on start with exit 132 (SIGILL), on an Apple M4 Max with Docker Desktop 4.37.2. `minio --version` ran but `minio server` did not, and `minio/minio` is no longer on Docker Hub. Updating Docker Desktop fixed it, with the compose file unchanged.
- **Pending:** the video.

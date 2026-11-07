# Interface comparison

The interface is under `analysis/review_app/`. It reads traces live from Langfuse. Run it with `uv run python -m analysis.review_app.server`.

## What the standard Langfuse view made harder

I read 9 traces from 7 conversations in the Langfuse annotation queue `hw4-preliminary`. They were chosen by role, turn count and tools used, not by outcome. My notes:

- Tool results are a few steps away from the reply that describes them. I have to click back and forth to view them.
- I don't always see the policy text.
- Earlier turns and context aren't easy to see in Langfuse.
- I can attach comments to individual spans, but not the overall trace.

## One design retained from the reference interface

A standard-library Python server over plain JSON files in `analysis/state/`, with one self-contained HTML page. It also keeps the reference's color per role and its shared container for a tool call and its result. Every decision stays inspectable and reviewable in git, and the page needs no build step.

## One design changed after inspecting my traces

The reference renders the shared normalizer's output, one trace at a time. Reading my traces showed that this hides evidence. Generation outputs are empty on all 697 generations, so the normalizer keeps only each turn's final reply. It drops 322 agent text steps and 257 thinking blocks across the 365 traces.

My interface rebuilds each turn from the last generation's input, in the order the model produced the steps, and checks it against the tool spans (387 of 387 tool calls match). It groups turns by `cartwheel.session_id`, and it marks agent steps as not shown to the user, because the server returns only the final output.

Each turn also has its own note box beside it. A note belongs to the trace, with an optional quote, in place of the reference's highlight-only notes and my note about span-only comments in Langfuse.

## One limitation remaining

Open codes stay in `analysis/state/annotations.json`; only accepted judgments reach Langfuse, as scores. The interface also can't look up arbitrary records, because `data/cartwheel.db` changed during the run, so checking a fact the trace doesn't show needs the scenario's answer key or a separate read-only query against a freshly seeded copy. The thinking behind each final reply isn't in the traces at all.

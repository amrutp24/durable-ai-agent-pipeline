# I Built an AI Agent Team That Sleeps for Free — Thanks to AWS's Newest Lambda Feature

Every serverless AI workflow I've built has hit the same wall: the moment a human needs to review something, you're stuck. Step Functions can wait, sure, but now you're paying for a state machine, wiring up a callback pattern, and hoping the payload fits. A "durable" Lambda felt like a contradiction — Lambda is famous for *not* being durable, for forgetting everything the second it's done.

Then AWS shipped **Lambda durable functions** at re:Invent 2025, and it's exactly what it sounds like: a Lambda function that can pause — for ten seconds or for ten months — without you paying a cent while it's paused, and pick up exactly where it left off. AWS's own launch content pointed straight at multi-agent AI workflows and human-in-the-loop approvals as the reason this exists. So I built one.

## What I built

A three-agent content pipeline:

1. **Researcher agent** turns a topic into an outline
2. **Writer agent** drafts a post from that outline
3. **Editor agent** scores the draft 1–10 and, if it's not good enough, sends it back to the writer with feedback — a real revision loop, not a fixed pipeline

Once the editor is happy, the whole thing **suspends** and waits for a human to approve or reject the draft. That wait can last minutes, hours, or a full day, and during that time the function isn't running, isn't billed, and isn't costing anything. When someone calls the approve endpoint, Lambda wakes the function back up mid-execution and it finishes the job — publishing the final draft to S3.

All three agents are just one cheap model — Claude Haiku 4.5 on Bedrock — called with different system prompts. The interesting part isn't the model; it's the orchestration.

## The core idea: steps and waits

The durable execution SDK gives your handler a `DurableContext` instead of the usual Lambda context. Two operations matter here:

- **`context.step(...)`** runs a chunk of business logic and checkpoints the result. If the function is interrupted later, it doesn't re-run — Lambda replays the stored result instead.
- **`context.wait_for_callback(...)`** hands you a `callback_id`, suspends the function, and resumes it only when something outside the function calls back with that ID.

Here's the shape of the orchestrator, trimmed down:

```python
from aws_durable_execution_sdk_python import DurableContext, durable_execution
from aws_durable_execution_sdk_python.config import Duration, WaitForCallbackConfig

@durable_execution
def lambda_handler(event, context: DurableContext):
    topic = event["topic"]

    outline = context.step(lambda _: call_agent(RESEARCH_PROMPT, topic), name="research")
    draft = context.step(lambda _: call_agent(WRITE_PROMPT, f"{topic}\n{outline}"), name="write-0")

    for revision in range(MAX_REVISIONS):
        critique = json.loads(
            context.step(lambda _: call_agent(EDIT_PROMPT, draft), name=f"critique-{revision}")
        )
        if critique["score"] >= APPROVAL_SCORE_THRESHOLD:
            break
        draft = context.step(
            lambda _: call_agent(REVISE_PROMPT, f"{draft}\n{critique['feedback']}"),
            name=f"write-{revision + 1}",
        )

    def request_approval(callback_id, _ctx):
        # store callback_id + draft in DynamoDB so an API route can find it later
        set_status(execution_id, callback_id=callback_id, draft=draft, status="AWAITING_APPROVAL")

    # The callback result is whatever raw string the external caller sent -
    # no automatic JSON parsing, so we decode it ourselves.
    approval_raw = context.wait_for_callback(
        request_approval,
        name="human-approval",
        config=WaitForCallbackConfig(timeout=Duration.from_seconds(86400)),
    )
    approval = json.loads(approval_raw) if approval_raw else None

    if not approval or not approval.get("approved"):
        return {"status": "REJECTED"}

    final_url = context.step(lambda _: publish_to_s3(draft), name="publish")
    return {"status": "PUBLISHED", "url": final_url}
```

Two things surprised me while building this:

**The revision loop is just... a for loop.** No state machine JSON, no extra Lambda per revision, no Step Functions "Choice" state. The editor's decision (`score >= threshold`) is a plain Python `if`, and because the score came from a checkpointed step, it's safe to branch on it — replays don't recompute it, they reuse the stored value.

**The wait genuinely costs nothing.** I left a test run sitting at `AWAITING_APPROVAL` overnight. No Lambda duration billed, no polling Lambda spinning in a loop burning invocations, no Step Functions per-transition cost. It's just... gone until someone calls back.

**The callback permission has a gotcha.** My first approval attempt failed with `AccessDeniedException` even though I'd granted `lambda:SendDurableExecutionCallbackSuccess` on the function's ARN. The callback resource is actually a *sub-resource of the versioned function ARN* — `...function:my-fn:2/durable-execution/<execution-id>/<callback-id>` — so the bare function ARN never matches. The IAM resource needs a trailing wildcard: `"${function_arn}:*"`.

**The published docs and the installed SDK didn't quite agree.** This feature is a few months old, and the SDK is still on major version 1 — AWS explicitly warns you to pin it for exactly this reason. The doc examples show a one-argument `callback_id` submitter and a plain `timeout=86400`; the version I actually `pip install`-ed wants a two-argument submitter and a `Duration.from_seconds(86400)` wrapped in a `WaitForCallbackConfig`. Nothing broke silently — Python just told me the import didn't exist — but it's a good reminder to `pip show` and read the installed source instead of trusting docs verbatim on anything this new.

## Getting a human into the loop

The approval side lives behind a small API Gateway HTTP API, handled by a plain (non-durable) Lambda:

- `POST /posts` — kicks off a run, returns an `execution_id`
- `GET /posts/{id}` — check status and read the current draft
- `POST /posts/{id}/approve` — approve or reject

The approve route does the one piece of glue that makes the callback pattern work — it looks up the `callback_id` DynamoDB stashed away when the orchestrator paused, then tells Lambda the callback succeeded:

```python
lambda_client.send_durable_execution_callback_success(
    CallbackId=item["callback_id"],
    Result=json.dumps({"approved": approved}),
)
```

That single call is what wakes the orchestrator back up, replays its checkpoint log, and lets it fall through into the publish step.

## Running it end to end

```bash
curl -X POST "$API/posts" -d '{"topic": "why idle compute shouldn'\''t cost money"}'
# {"execution_id": "a1b2...", "status": "STARTED"}

curl "$API/posts/a1b2..."
# {"status": "AWAITING_APPROVAL", "draft": "# Why Idle Compute...\n\n..."}

curl -X POST "$API/posts/a1b2.../approve" -d '{"approved": true}'

curl "$API/posts/a1b2..."
# {"status": "PUBLISHED", "final_url": "s3://.../a1b2....md"}
```

Watching it in the Lambda console's **Durable executions** tab is honestly the best part — you see every checkpoint, the exact moment it suspends, and the replay when it wakes back up.

One more field note: my first live run died at the critique step because the editor agent wrapped its JSON in markdown code fences — despite being told not to. The fix is a five-line fence-stripping helper before `json.loads`, and because I only changed code *after* the failed step, redeploying and re-running was painless. (In-flight executions stay pinned to the version that started them, which is exactly what you want here.)

## Where this actually matters

Swap "blog post" for anything that needs a human sign-off before something irreversible happens — a refund, a support macro, a deploy, a contract clause — and the pattern holds. That's the pitch AWS is making with this feature, and having now built it, I believe it: the alternative (Step Functions + a callback token, or a Lambda + SQS + a polling worker) is more moving parts for the same guarantee.

## Try it yourself

The full Terraform + Lambda code is on GitHub: `durable-ai-agent-pipeline`. It deploys in a few minutes — `terraform apply` — and costs a few cents per run since the wait is free. Instructions and a troubleshooting table are in the README.

If you're also trying to get hands-on with agentic AI on AWS, durable functions are a genuinely fun on-ramp: you get to write the *judgment* part of an agent (should I retry? should I wait? should I stop?) as plain, boring, readable code — no orchestration DSL required.

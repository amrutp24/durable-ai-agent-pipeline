# Screenshot shot-list for the Medium article

All of these exist right now in the `dev` account (us-east-1) from today's verified
runs. Crop out the account ID (top-right) before publishing.

## 1. The money shot: durable execution timeline ⭐

**Lambda console → Functions → `durable-ai-agent-orchestrator` → Durable executions tab → click the succeeded execution**

Shows every checkpoint (research, write-0, critique-0, …), the exact moment the
function suspended at `human-approval`, the gap while it waited (zero compute),
and the resume + publish after approval. This single image explains the whole
article.

Succeeded execution to use: the one started ~9:10 PM CT on Jul 5
(execution for run `49861de3-...` — topic "what AWS Lambda durable functions
change for AI agents").

## 2. The suspend/replay in the logs

**CloudWatch → Log groups → `/aws/lambda/durable-ai-agent-orchestrator`**

Pick the log stream pair showing: first invocation ends after `wait_for_callback`,
second invocation (after approval) replays and goes straight to `publish`.
Highlights that the function was *invoked twice* but each agent step ran *once*.

## 3. The terminal session

Re-run the happy path and screenshot the terminal:

```bash
API=$(cd terraform && terraform output -raw api_endpoint)
curl -X POST "$API/posts" -d '{"topic": "anything"}'
curl "$API/posts/<id>"              # AWAITING_APPROVAL + draft
curl -X POST "$API/posts/<id>/approve" -d '{"approved": true}'
curl "$API/posts/<id>"              # PUBLISHED + s3 url
```

## 4. Durable config in the console

**Lambda console → `durable-ai-agent-orchestrator` → Configuration → Durable execution**

Shows Execution timeout (48h) and Retention period (7 days) — proof this is a
first-class Lambda feature, not a wrapper.

## 5. Billing guardrail (optional, for the cost section)

**Billing console → Budgets → `durable-ai-agent-monthly-budget`**

The $50 budget with its 4 alert thresholds.

## 6. Architecture diagram

Use `diagram.svg` in this repo (renders on GitHub; export to PNG for Medium via
any browser: open the file → screenshot, or use Inkscape/`rsvg-convert`).

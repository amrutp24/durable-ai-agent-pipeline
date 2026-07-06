# Screenshot shot-list for the Medium article

All console links: us-east-1, function `durable-ai-agent-orchestrator`.
Crop out the AWS account ID (top-right) before publishing.

## 1. The money shot: durable execution timeline ⭐

**Lambda console → Functions → `durable-ai-agent-orchestrator` → Durable executions tab → click a Succeeded execution's ID** (don't screenshot the list — click into one).

The detail page shows the operation timeline: the `research` / `write-0` /
`critique-0` steps, the `human-approval` **WaitForCallback** with its start and
end timestamps (the visible gap = suspended at $0), then `publish`. That gap is
the whole article in one image.

If your screenshot is of the executions *list*, retake it from the detail page.

## 2. Proof it was invoked twice (suspend → resume)

Skip grepping logs for `wait_for_callback` — the code never logs that string.
The evidence of suspend/resume is **two separate invocations for one
execution**:

- Easiest: on the same execution detail page as shot 1, the events list shows
  the execution suspending at `human-approval` and a new invocation resuming it
  after the callback.
- In CloudWatch (optional): log group `/aws/lambda/durable-ai-agent-orchestrator`
  — you'll see **two `START RequestId` / `REPORT RequestId` pairs** bracketing
  the approval gap. Different request IDs, one execution: that's checkpoint/replay.

## 3. The terminal session (PowerShell)

The earlier bash commands mangle JSON quoting on Windows (that was your
"Internal Server Error"). Paste this instead — it's PowerShell-native:

```powershell
$API = "https://pu4aazbz39.execute-api.us-east-1.amazonaws.com"

# Start a run
$run = Invoke-RestMethod -Method Post -Uri "$API/posts" -ContentType "application/json" `
  -Body (@{ topic = "why idle compute shouldn't cost money" } | ConvertTo-Json)
$run

# Poll until it's waiting on you (repeat this line every ~20s)
Invoke-RestMethod "$API/posts/$($run.execution_id)" | Format-List status, topic

# Approve it
Invoke-RestMethod -Method Post -Uri "$API/posts/$($run.execution_id)/approve" `
  -ContentType "application/json" -Body '{"approved": true}'

# Confirm published
Invoke-RestMethod "$API/posts/$($run.execution_id)" | Format-List status, final_url
```

Screenshot the whole sequence once the last call shows `PUBLISHED`.

## 4. Durable config (execution timeout + retention)

**Lambda console → `durable-ai-agent-orchestrator` → Configuration tab →
"Durable execution" in the left sidebar** (same sidebar as General
configuration / Triggers / Permissions — scroll the sidebar if needed).

Expected values: **Execution timeout 172800 s (48 h)**, **Retention 7 days**.

If your console doesn't show that sidebar entry, screenshot this instead from
the repo root (the local `aws` CLI is too old for durable fields; this uses the
newer bundled boto3):

```powershell
cd build\api
$env:AWS_PROFILE = "dev"
python -c "import sys; sys.path.insert(0,'.'); import boto3,json; print(json.dumps(boto3.client('lambda', region_name='us-east-1').get_function_configuration(FunctionName='durable-ai-agent-orchestrator')['DurableConfig'], indent=2))"
```

## 5. Billing (optional — skip if unsure)

Purely optional flavor for the cost section; the article stands without it.
If you want it: **Billing console → Budgets → `durable-ai-agent-monthly-budget`**.
It has no impact on anything — it's just your alert's threshold page.

## 6. Architecture diagram

`diagram.svg` renders on GitHub; export to PNG for Medium (open in browser →
screenshot, or Inkscape).

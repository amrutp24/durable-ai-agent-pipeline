# Durable AI Agent Pipeline 🤖⏸️

A multi-agent content pipeline (researcher → writer → editor, with a self-correcting revision loop) that pauses for **free** while it waits on human approval — built on **AWS Lambda durable functions**, the checkpoint/replay execution model AWS shipped at re:Invent 2025.

- ☁️ **AWS Lambda durable functions** — the orchestrator, checkpointed step-by-step
- 🧠 **Amazon Bedrock** (Claude Haiku 4.5) — three agent roles, one model
- 🗄️ **DynamoDB** — tracks pipeline status + the pending draft
- 🪣 **S3** — where approved posts get published
- 🌐 **API Gateway HTTP API** — start a run, check status, approve/reject
- 🏗️ **Terraform** via the reusable [terraform-aws-durable-agent-pipeline](https://github.com/amrutp24/terraform-aws-durable-agent-pipeline) module (AWS provider ≥ 6.25.0, which added `durable_config` support)

## Why this is interesting

Lambda durable functions let a function suspend mid-execution — for seconds or for up to a year — **without paying for idle compute**, then resume exactly where it left off. That's a genuinely new primitive, and AWS's own launch content points at multi-agent AI workflows and human-in-the-loop approvals as the flagship use case. This project builds that exact pattern end to end: three LLM "agents" cooperating in a loop, then a durable wait for a human to say yes/no, at no cost while it waits.

## Project structure

All AWS resources live in the reusable Terraform module [terraform-aws-durable-agent-pipeline](https://github.com/amrutp24/terraform-aws-durable-agent-pipeline); this repo holds the application code and the root config that consumes the module.

```
durable-ai-agent-pipeline/
├── terraform/              # Root config: consumes the module + billing alert
│   ├── main.tf             # module "agent_pipeline" { ... }
│   ├── billing.tf          # AWS Budgets $50/month alert
│   ├── provider.tf
│   ├── variables.tf        # No defaults - ALL config comes from dev.tfvars
│   ├── outputs.tf
│   └── dev.tfvars.example  # Copy to dev.tfvars (gitignored) and fill in
├── src/
│   ├── orchestrator/       # The durable function: research → write → edit → wait → publish
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   └── api/                # Plain Lambda behind API Gateway (start/status/approve)
│       └── lambda_function.py
└── scripts/
    └── build.sh            # Vendors the durable execution SDK for the orchestrator
```

## How the pipeline works

```
POST /posts {"topic": "..."}
      │
      ▼  API Lambda: record run in DynamoDB, async-invoke the prod alias
┌────────────────────────────────────────────────────────────────┐
│ Durable orchestrator — every (step) is checkpointed            │
│                                                                │
│   research (step)                                              │
│       │                                                        │
│       ▼                                                        │
│   write (step)                                                 │
│       │                                                        │
│       ▼                                                        │
│   critique (step) ◄────────────────────┐                       │
│       │                                │                       │
│       ├── score < 8 ──► revise (step) ─┘  (max 2 revisions)    │
│       │                                                        │
│       ▼  score ≥ 8 (or revision limit reached)                 │
│   wait_for_callback("human-approval")                          │
│   suspended — $0 compute — up to 24 h                          │
│       │                                                        │
│       │ ◄─── human: POST /posts/{id}/approve                   │
│       │              {"approved": true | false}                │
│       │                                                        │
│       ├── approved ──► publish (step) ──► S3, status=PUBLISHED │
│       │                                                        │
│       └── rejected or 24 h timeout ──► status = REJECTED       │
└────────────────────────────────────────────────────────────────┘
```

Every arrow into a `(step)` is a checkpoint: if the function fails or gets interrupted after `write`, a retry resumes at `critique` instead of re-running (and re-billing) the writer agent.

## Prerequisites

- AWS account with **Bedrock model access** granted for `anthropic.claude-haiku-4-5-20251001-v1:0` in your target region (Bedrock console → Model access)
- Terraform ≥ 1.5, AWS provider will be pulled at ≥ 6.25.0
- Python 3.13 + pip (to build the orchestrator's deployment package)
- AWS CLI configured with credentials that can create Lambda/DynamoDB/S3/API Gateway/IAM resources

## Deploy

```bash
cd durable-ai-agent-pipeline

# 1. Package the orchestrator (bundles the durable execution SDK)
./scripts/build.sh

# 2. Deploy
cd terraform
cp dev.tfvars.example dev.tfvars   # fill in profile/region/email - dev.tfvars is gitignored
terraform init
terraform apply -var-file="dev.tfvars"
```

All configuration (AWS profile, region, model, agent tuning, budget email) lives in `dev.tfvars`, which is **gitignored** — nothing environment-specific or personal is committed. The root variables have no defaults, so Terraform will refuse to run without it.

The module is consumed from a local sibling path by default; once it's on the Terraform Registry you can switch `terraform/main.tf` to:

```hcl
source  = "amrutp24/durable-agent-pipeline/aws"
version = "~> 1.0"
```

## Cost controls

- **Reserved concurrency** variables cap runaway Lambda invocations (disabled with `-1` on accounts whose total concurrency limit is ≤50, since AWS requires 50 unreserved).
- Durable waits bill **nothing** while suspended; DynamoDB is pay-per-request; CloudWatch logs expire after 14 days.
- `terraform/billing.tf` additionally sets up a personal account-level AWS Budgets alert for whoever deploys this (`monthly_budget_usd` / `billing_alert_email` in tfvars). It's deployer-side protection, unrelated to the pipeline — delete the file if you don't want it.

Note the `api_endpoint` output when it finishes.

## Try it

```bash
API=<api_endpoint from terraform output>

# Kick off a run
curl -s -X POST "$API/posts" -d '{"topic": "why idle compute shouldn'\''t cost money"}' | tee /tmp/run.json
ID=$(jq -r .execution_id /tmp/run.json)

# Poll status - watch it go STARTED -> AWAITING_APPROVAL
curl -s "$API/posts/$ID" | jq

# Read the draft in that response, then approve or reject it
curl -s -X POST "$API/posts/$ID/approve" -d '{"approved": true}'

# Confirm it published
curl -s "$API/posts/$ID" | jq
aws s3 cp "s3://$(cd ../terraform && terraform output -raw posts_bucket)/$ID.md" -
```

You can also watch the run in the Lambda console under **Durable executions** — it shows every checkpoint, the wait, and the replay when it resumes.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `AccessDeniedException` calling Bedrock | Model access for the model in `model_id` isn't granted in that region yet |
| `terraform apply` fails on `durable_config` | AWS provider is pinned below 6.25.0 — run `terraform init -upgrade` |
| `/posts/{id}/approve` returns 409 | Run isn't at `AWAITING_APPROVAL` yet — poll `/posts/{id}` until the editor loop finishes |
| Approve request errors with `CallbackTimeoutException` | `callback_timeout_seconds` expired before you approved; re-run the pipeline |
| Approve returns 500 with `AccessDeniedException` right after deploy | Callback ARNs are sub-resources of the versioned function ARN, so the IAM resource must be `"${function_arn}:*"` (already in `iam.tf`); fresh IAM changes can also take ~1 min to propagate |
| Orchestrator import errors for `aws_durable_execution_sdk_python` | Re-run `scripts/build.sh` — it wasn't packaged, or `build/orchestrator` is stale |

## Cost

Bedrock Haiku calls (5-7 per run) and a handful of Lambda invocations — a few cents per run. The whole point of the durable wait is that the hours spent waiting for approval cost **nothing**.

## Cleanup

```bash
cd terraform
terraform destroy -var-file="dev.tfvars"
```

## License

MIT — see [LICENSE](LICENSE).

## Author

Amrut Pagidipally

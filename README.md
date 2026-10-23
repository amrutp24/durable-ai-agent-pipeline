# Durable AI Agent Pipeline

A content pipeline with three Bedrock "agents" (researcher, writer, editor) that revise a draft in a loop, then pause until a person approves or rejects it. It runs on AWS Lambda durable functions, the checkpoint-and-replay execution model AWS released at re:Invent 2025. While the pipeline waits for approval it is suspended, and suspended functions aren't billed for compute.

It uses:

- Lambda durable functions for the orchestrator, checkpointed step by step
- Amazon Bedrock, with Claude Haiku 4.5 for all three agent roles
- DynamoDB for run status and the pending draft
- S3 for approved posts
- API Gateway (HTTP API) to start a run, check its status, and approve or reject it
- Terraform, through the [terraform-aws-durable-agent-pipeline](https://registry.terraform.io/modules/amrutp24/durable-agent-pipeline/aws/latest) module (AWS provider 6.25.0 or later, which added `durable_config`)

Write-ups:

- [Lambda functions can pause for free now. I built an AI agent pipeline to test that.](https://amruteng.medium.com/lambda-functions-can-pause-for-free-now-i-built-an-ai-agent-pipeline-to-test-that-66c2623fb7a7)
- [I blogged about an AWS docs gap. Eight days later, AWS closed it.](https://amruteng.medium.com/i-blogged-about-an-aws-docs-gap-eight-days-later-aws-closed-it-f335d81d8a7e), about the callback IAM permission that wasn't documented when this was built

## Why durable functions

A durable function can suspend partway through a run, for anything from seconds to a year, and resume where it stopped. Steps that already completed aren't run again. AWS's launch material uses multi-agent AI workflows and human approvals as the main example, and this project builds that case: agents working in a loop, then a wait for a person, with no compute billed during the wait.

## Project structure

All AWS resources are created by the Terraform module. This repo holds the application code and the root configuration that uses the module.

```
durable-ai-agent-pipeline/
├── terraform/              # root config: uses the module, plus a billing alert
│   ├── main.tf             # module "agent_pipeline" { ... }
│   ├── billing.tf          # AWS Budgets monthly alert
│   ├── provider.tf
│   ├── variables.tf        # no defaults; all config comes from dev.tfvars
│   ├── outputs.tf
│   └── dev.tfvars.example  # copy to dev.tfvars (gitignored) and fill in
├── src/
│   ├── orchestrator/       # the durable function: research, write, edit, wait, publish
│   │   ├── lambda_function.py
│   │   └── requirements.txt
│   └── api/                # plain Lambda behind API Gateway (start, status, approve)
│       └── lambda_function.py
└── scripts/
    └── build.sh            # vendors the durable execution SDK for the orchestrator
```

## How the pipeline works

```
POST /posts {"topic": "..."}
      │
      ▼  API Lambda: record run in DynamoDB, async-invoke the prod alias
┌────────────────────────────────────────────────────────────────┐
│ Durable orchestrator. Every (step) is checkpointed.            │
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
│       ▼  score ≥ 8, or revision limit reached                  │
│   wait_for_callback("human-approval")                          │
│   suspended, no compute billed, up to 24 h                     │
│       │                                                        │
│       │ ◄─── human: POST /posts/{id}/approve                   │
│       │              {"approved": true | false}                │
│       │                                                        │
│       ├── approved ──► publish (step) ──► S3, status=PUBLISHED │
│       │                                                        │
│       └── rejected or 24 h timeout ──► status = REJECTED       │
└────────────────────────────────────────────────────────────────┘
```

Each `(step)` is a checkpoint. If the function fails after `write`, a retry resumes at `critique` instead of running (and paying for) the writer again.

After the last allowed revision, the draft goes to approval without another critique. The score threshold, revision limit and approval timeout come from `approval_score_threshold`, `max_revisions` and `callback_timeout_seconds`; the values above are the ones in `dev.tfvars.example`.

## Prerequisites

- An AWS account with Bedrock model access for Claude Haiku 4.5 in your region (Bedrock console, Model access). The example config uses the `us.anthropic.claude-haiku-4-5-20251001-v1:0` inference profile.
- Terraform 1.5 or later. `terraform init` pulls AWS provider 6.25.0 or later.
- Python 3.13 and pip, to build the orchestrator package
- AWS CLI with credentials that can create Lambda, DynamoDB, S3, API Gateway and IAM resources

## Deploy

```bash
cd durable-ai-agent-pipeline

# 1. Package the orchestrator (bundles the durable execution SDK)
./scripts/build.sh

# 2. Deploy
cd terraform
cp dev.tfvars.example dev.tfvars   # fill in profile, region and email; dev.tfvars is gitignored
terraform init
terraform apply -var-file="dev.tfvars"
```

Note the `api_endpoint` output when it finishes.

All configuration (AWS profile, region, model, agent settings, budget email) lives in `dev.tfvars`, which is gitignored, so nothing environment-specific is committed. The root variables have no defaults, so Terraform won't run without it.

`main.tf` pulls the module from the Terraform Registry. To work on the module locally, change `source` to a sibling checkout of [terraform-aws-durable-agent-pipeline](https://github.com/amrutp24/terraform-aws-durable-agent-pipeline); the line to use is in a comment in `main.tf`.

## Try it

```bash
API=<api_endpoint from terraform output>

# Start a run
curl -s -X POST "$API/posts" -d '{"topic": "why idle compute shouldn'\''t cost money"}' | tee /tmp/run.json
ID=$(jq -r .execution_id /tmp/run.json)

# Poll the status until it goes from STARTED to AWAITING_APPROVAL
curl -s "$API/posts/$ID" | jq

# Read the draft in that response, then approve or reject it
curl -s -X POST "$API/posts/$ID/approve" -d '{"approved": true}'

# Confirm it published
curl -s "$API/posts/$ID" | jq
aws s3 cp "s3://$(cd ../terraform && terraform output -raw posts_bucket)/$ID.md" -
```

The Lambda console also shows each run under **Durable executions**, including every checkpoint, the wait, and the replay when it resumes.

## Cost

Each run makes 3 to 6 Bedrock calls to Haiku (3 if the first draft passes, 6 with two revisions) plus a few Lambda invocations, which comes to a few cents. Time spent waiting for approval isn't billed.

Cost controls:

- Reserved concurrency variables cap Lambda invocations. Set them to `-1` on accounts whose total concurrency limit is 50 or lower, because AWS requires 50 to stay unreserved.
- DynamoDB is pay-per-request, and CloudWatch logs expire after 14 days.
- `terraform/billing.tf` adds an account-level AWS Budgets alert for whoever deploys this (`monthly_budget_usd` and `billing_alert_email` in `dev.tfvars`). It protects the deployer's account and has nothing to do with the pipeline, so delete the file if you don't want it.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `AccessDeniedException` calling Bedrock | Model access for the model in `model_id` isn't granted in that region yet. |
| `terraform apply` fails on `durable_config` | The AWS provider is below 6.25.0. Run `terraform init -upgrade`. |
| `/posts/{id}/approve` returns 409 | The run isn't at `AWAITING_APPROVAL` yet. Poll `/posts/{id}` until the editor loop finishes. |
| Approving fails with `CallbackTimeoutException` | `callback_timeout_seconds` passed before you approved. Start a new run. |
| Approve returns 500 with `AccessDeniedException` right after deploy | Callback ARNs are sub-resources of the versioned function ARN, so the IAM resource has to be `"${function_arn}:*"`. The module already sets this; new IAM policies can take about a minute to propagate. |
| Orchestrator import errors for `aws_durable_execution_sdk_python` | The SDK wasn't packaged, or `build/orchestrator` is out of date. Re-run `scripts/build.sh`. |

## Cleanup

```bash
cd terraform
terraform destroy -var-file="dev.tfvars"
```

## License

MIT. See [LICENSE](LICENSE).

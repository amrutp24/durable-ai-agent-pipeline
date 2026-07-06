variable "aws_profile" {
  description = "AWS CLI profile to use for credentials."
  type        = string
}

variable "aws_region" {
  description = "AWS region to deploy into. Must have Bedrock model access granted for the chosen model."
  type        = string
}

variable "project_name" {
  description = "Prefix used for all resource names."
  type        = string
}

variable "model_id" {
  description = "Bedrock model or inference-profile ID used by every agent step."
  type        = string
}

variable "max_revisions" {
  description = "Max writer/editor revision loops before the draft goes to human approval regardless of score."
  type        = number
}

variable "approval_score_threshold" {
  description = "Editor score (1-10) at or above which the draft is considered good enough."
  type        = number
}

variable "callback_timeout_seconds" {
  description = "How long the orchestrator waits for human approval before giving up."
  type        = number
}

variable "durable_execution_timeout_seconds" {
  description = "Max total lifetime of one durable execution (steps + waits combined)."
  type        = number
}

variable "durable_retention_period_days" {
  description = "How long Lambda retains checkpoint/execution history after completion."
  type        = number
}

variable "lambda_alias_name" {
  description = "Alias name for the orchestrator's published version (durable functions require a qualified ARN)."
  type        = string
}

variable "orchestrator_reserved_concurrency" {
  description = "Reserved concurrency for the orchestrator - cost guardrail. -1 for unreserved."
  type        = number
}

variable "api_reserved_concurrency" {
  description = "Reserved concurrency for the API Lambda - cost guardrail. -1 for unreserved."
  type        = number
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD; alerts fire at 50/80/100% and on forecast."
  type        = string
}

variable "billing_alert_email" {
  description = "Email address that receives budget alert notifications."
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
}

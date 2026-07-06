# Packages are built by scripts/build.sh into ../build/{orchestrator,api},
# zipped here, and handed to the module as pre-built artifacts.

data "archive_file" "orchestrator" {
  type        = "zip"
  source_dir  = "${path.module}/../build/orchestrator"
  output_path = "${path.module}/../build/orchestrator.zip"
}

data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../build/api"
  output_path = "${path.module}/../build/api.zip"
}

module "agent_pipeline" {
  # Local path while developing; after publishing to the Terraform Registry,
  # switch to:
  #   source  = "amrutp24/durable-agent-pipeline/aws"
  #   version = "~> 1.0"
  source = "../../terraform-aws-durable-agent-pipeline"

  project_name         = var.project_name
  orchestrator_package = data.archive_file.orchestrator.output_path
  api_package          = data.archive_file.api.output_path

  model_id                          = var.model_id
  max_revisions                     = var.max_revisions
  approval_score_threshold          = var.approval_score_threshold
  callback_timeout_seconds          = var.callback_timeout_seconds
  durable_execution_timeout_seconds = var.durable_execution_timeout_seconds
  durable_retention_period_days     = var.durable_retention_period_days

  lambda_alias_name                 = var.lambda_alias_name
  orchestrator_reserved_concurrency = var.orchestrator_reserved_concurrency
  api_reserved_concurrency          = var.api_reserved_concurrency

  tags = var.tags
}

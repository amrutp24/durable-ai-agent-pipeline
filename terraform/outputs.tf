output "api_endpoint" {
  description = "Base URL for the HTTP API."
  value       = module.agent_pipeline.api_endpoint
}

output "orchestrator_qualified_arn" {
  description = "Qualified ARN (prod alias) of the durable orchestrator function."
  value       = module.agent_pipeline.orchestrator_qualified_arn
}

output "posts_bucket" {
  description = "S3 bucket that published drafts land in."
  value       = module.agent_pipeline.posts_bucket
}

output "executions_table" {
  description = "DynamoDB table tracking pipeline run status."
  value       = module.agent_pipeline.executions_table
}

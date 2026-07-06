# Account-level monthly cost budget with email alerts. AWS Budgets emails the
# subscriber directly - no SNS topic needed. Note: budgets alert, they don't
# hard-stop spend; the hard guardrails are reserved concurrency on the Lambdas
# and pay-per-request DynamoDB.

resource "aws_budgets_budget" "monthly_cost" {
  name         = "${var.project_name}-monthly-budget"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Warn early at 50% of actual spend...
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  # ...again at 80% actual...
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  # ...at 100% actual (the $50 line itself)...
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.billing_alert_email]
  }

  # ...and as soon as the month's *forecast* crosses the line, before it happens.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.billing_alert_email]
  }
}

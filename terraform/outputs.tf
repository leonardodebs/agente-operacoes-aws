# Outputs consumidos por scripts, README e pelo workflow de deploy.

output "agent_id" {
  description = "ID do Bedrock Agent."
  value       = aws_bedrockagent_agent.infra_ops.agent_id
}

output "agent_alias_id" {
  description = "ID do alias do agente usado para invocacao."
  value       = aws_bedrockagent_agent_alias.live.agent_alias_id
}

output "tools_function_name" {
  description = "Nome da Lambda de ferramentas."
  value       = aws_lambda_function.tools.function_name
}

output "slack_function_name" {
  description = "Nome da Lambda do Slack."
  value       = aws_lambda_function.slack.function_name
}

output "slack_function_url" {
  description = "URL publica da Lambda do Slack (configure no app Slack)."
  value       = aws_lambda_function_url.slack.function_url
}

output "history_table" {
  description = "Tabela DynamoDB de historico de conversas."
  value       = aws_dynamodb_table.history.name
}

output "slack_secret_arn" {
  description = "ARN do secret com os tokens do Slack."
  value       = aws_secretsmanager_secret.slack.arn
}

output "github_actions_role_arn" {
  description = "ARN da role assumida pelo GitHub Actions via OIDC."
  value       = aws_iam_role.github_actions.arn
}

output "dashboard_name" {
  description = "Nome do CloudWatch Dashboard."
  value       = aws_cloudwatch_dashboard.infra_ops.dashboard_name
}

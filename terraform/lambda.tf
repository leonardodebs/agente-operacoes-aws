# Lambdas: ferramentas (action group) e handler do Slack (Function URL).

# -----------------------------------------------------------------------------
# Lambda de ferramentas - implementa as 9 ferramentas SOMENTE LEITURA.
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "tools" {
  function_name = var.tools_function_name
  role          = aws_iam_role.tools.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 256

  filename         = data.archive_file.tools_zip.output_path
  source_code_hash = data.archive_file.tools_zip.output_base64sha256

  environment {
    variables = {
      DEFAULT_REGION = var.aws_region
    }
  }
}

resource "aws_cloudwatch_log_group" "tools" {
  name              = "/aws/lambda/${var.tools_function_name}"
  retention_in_days = var.log_retention_days
}

# Permite que o Bedrock invoque a Lambda de ferramentas em nome do agente.
resource "aws_lambda_permission" "bedrock_invoke_tools" {
  statement_id  = "AllowBedrockAgentInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.infra_ops.agent_arn
}

# -----------------------------------------------------------------------------
# Lambda do Slack - recebe eventos via Function URL e invoca o agente.
# -----------------------------------------------------------------------------
resource "aws_lambda_function" "slack" {
  function_name = var.slack_function_name
  role          = aws_iam_role.slack.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 512

  filename         = data.archive_file.slack_zip.output_path
  source_code_hash = data.archive_file.slack_zip.output_base64sha256

  environment {
    variables = {
      DEFAULT_REGION         = var.aws_region
      BEDROCK_AGENT_ID       = aws_bedrockagent_agent.infra_ops.agent_id
      BEDROCK_AGENT_ALIAS_ID = aws_bedrockagent_agent_alias.live.agent_alias_id
      HISTORY_TABLE          = aws_dynamodb_table.history.name
      SLACK_SECRET_ARN       = aws_secretsmanager_secret.slack.arn
    }
  }
}

resource "aws_cloudwatch_log_group" "slack" {
  name              = "/aws/lambda/${var.slack_function_name}"
  retention_in_days = var.log_retention_days
}

# Function URL publica (o Slack chama aqui). A autenticidade e garantida pela
# validacao de assinatura HMAC no codigo, nao por IAM.
resource "aws_lambda_function_url" "slack" {
  function_name      = aws_lambda_function.slack.function_name
  authorization_type = "NONE"
}

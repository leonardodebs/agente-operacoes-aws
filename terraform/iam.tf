# IAM - principio do menor privilegio.
# Tools: somente LEITURA. Slack: invocar agente + DynamoDB + ler 1 secret.

# =============================================================================
# Role de execucao da Lambda de ferramentas (SOMENTE LEITURA)
# =============================================================================
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "tools" {
  name               = "${var.tools_function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "tools_logs" {
  role       = aws_iam_role.tools.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Permissoes de LEITURA dos servicos consultados pelas ferramentas.
# Acoes Describe/List/Get nao suportam restricao por recurso; a seguranca vem
# de serem todas somente leitura (nenhuma acao de escrita/delete e concedida).
data "aws_iam_policy_document" "tools_readonly" {
  statement {
    sid    = "InfraReadOnly"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "rds:Describe*",
      "ecs:Describe*",
      "ecs:List*",
      "elasticloadbalancing:Describe*",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "cloudwatch:DescribeAlarms",
      "s3:ListAllMyBuckets",
      "s3:GetBucketLocation",
      "ce:GetCostAndUsage",
      "guardduty:ListDetectors",
      "guardduty:ListFindings",
      "guardduty:GetFindings",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "tools_readonly" {
  name   = "${var.tools_function_name}-readonly"
  role   = aws_iam_role.tools.id
  policy = data.aws_iam_policy_document.tools_readonly.json
}

# =============================================================================
# Role de execucao da Lambda do Slack
# =============================================================================
resource "aws_iam_role" "slack" {
  name               = "${var.slack_function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "slack_logs" {
  role       = aws_iam_role.slack.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "slack_policy" {
  statement {
    sid       = "InvokeAgent"
    effect    = "Allow"
    actions   = ["bedrock:InvokeAgent"]
    resources = [aws_bedrockagent_agent_alias.live.agent_alias_arn]
  }

  statement {
    sid    = "ConversationHistory"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]
    resources = [aws_dynamodb_table.history.arn]
  }

  statement {
    sid       = "ReadSlackSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.slack.arn]
  }
}

resource "aws_iam_role_policy" "slack_policy" {
  name   = "${var.slack_function_name}-policy"
  role   = aws_iam_role.slack.id
  policy = data.aws_iam_policy_document.slack_policy.json
}

# =============================================================================
# Role do Bedrock Agent
# =============================================================================
data "aws_iam_policy_document" "agent_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    # Confia apenas em agentes desta conta (evita "confused deputy").
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "agent" {
  name               = "${var.agent_name}-role"
  assume_role_policy = data.aws_iam_policy_document.agent_assume.json
}

# Detecta inference profile cross-region (prefixo us./global.) e libera tanto o
# profile quanto o modelo base em todas as regioes para onde o profile roteia.
locals {
  modelo_eh_profile = can(regex("^(us|global)\\.", var.foundation_model))
  modelo_base       = replace(replace(var.foundation_model, "us.", ""), "global.", "")

  recursos_modelo = local.modelo_eh_profile ? [
    "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/${var.foundation_model}",
    "arn:aws:bedrock:*::foundation-model/${local.modelo_base}",
    ] : [
    "arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/${var.foundation_model}",
  ]
}

data "aws_iam_policy_document" "agent_policy" {
  statement {
    sid    = "InvokeModel"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = local.recursos_modelo
  }

  statement {
    sid       = "InvokeToolsLambda"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.tools.arn]
  }
}

resource "aws_iam_role_policy" "agent_policy" {
  name   = "${var.agent_name}-policy"
  role   = aws_iam_role.agent.id
  policy = data.aws_iam_policy_document.agent_policy.json
}

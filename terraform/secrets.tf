# Secrets Manager - tokens do Slack (nunca no codigo nem em variaveis de ambiente).
# O valor e preenchido FORA do Terraform (CLI/console) para nao versionar segredo.

resource "aws_secretsmanager_secret" "slack" {
  name        = "slack-tokens"
  description = "SLACK_BOT_TOKEN e SLACK_SIGNING_SECRET do InfraBot."
}

# Cria uma versao inicial com placeholders. Apos o apply, atualize com os valores
# reais via:  aws secretsmanager put-secret-value --secret-id slack-tokens \
#               --secret-string '{"SLACK_BOT_TOKEN":"xoxb-...","SLACK_SIGNING_SECRET":"..."}'
# O lifecycle ignore_changes evita que o Terraform sobrescreva o valor real depois.
resource "aws_secretsmanager_secret_version" "slack" {
  secret_id = aws_secretsmanager_secret.slack.id
  secret_string = jsonencode({
    SLACK_BOT_TOKEN      = "PREENCHER",
    SLACK_SIGNING_SECRET = "PREENCHER"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

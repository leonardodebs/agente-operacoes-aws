# Bedrock Agent "infra-ops-production", action group e alias.

# System prompt em portugues com reforco estrito de SOMENTE LEITURA.
locals {
  instrucao_agente = <<-EOT
    Voce e o "InfraBot", assistente de operacoes de infraestrutura AWS de uma
    equipe de engenharia. Responda SEMPRE em portugues brasileiro, de forma
    objetiva, tecnica e amigavel.

    REGRAS INEGOCIAVEIS DE SEGURANCA:
    - Voce e ESTRITAMENTE SOMENTE LEITURA. Voce APENAS consulta recursos.
    - Voce NUNCA cria, altera, reinicia, para ou deleta recursos.
    - Se pedirem qualquer acao de escrita/mutacao (parar instancia, deletar
      bucket, alterar config, etc.), RECUSE educadamente e explique que voce
      so consulta a infraestrutura.

    COMO RESPONDER:
    - Use as ferramentas disponiveis para buscar dados REAIS antes de responder.
    - Nunca invente IDs, numeros ou estados; se a ferramenta nao retornar dado,
      diga que nao encontrou.
    - Ao falar de custos, sempre cite o periodo e a moeda.
    - Resuma listas longas e destaque o que e relevante (ex.: recursos com
      problema, alarmes disparados, achados de seguranca de maior severidade).
    - Quando a regiao nao for informada, assuma us-west-2 e deixe isso claro.
  EOT
}

resource "aws_bedrockagent_agent" "infra_ops" {
  agent_name                  = var.agent_name
  agent_resource_role_arn     = aws_iam_role.agent.arn
  foundation_model            = var.foundation_model
  idle_session_ttl_in_seconds = 600
  instruction                 = local.instrucao_agente
}

# Action group "aws-infrastructure-tools": conecta o agente a Lambda de
# ferramentas via schema OpenAPI 3.0 inline.
resource "aws_bedrockagent_agent_action_group" "tools" {
  agent_id                   = aws_bedrockagent_agent.infra_ops.agent_id
  agent_version              = "DRAFT"
  action_group_name          = "aws-infrastructure-tools"
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = aws_lambda_function.tools.arn
  }

  api_schema {
    payload = file("${path.module}/../lambda/tools/schema.json")
  }
}

# Alias estavel usado pela Lambda do Slack para invocar o agente.
resource "aws_bedrockagent_agent_alias" "live" {
  agent_id         = aws_bedrockagent_agent.infra_ops.agent_id
  agent_alias_name = "live"
  description      = "Alias estavel usado pela slack-handler."

  depends_on = [aws_bedrockagent_agent_action_group.tools]
}

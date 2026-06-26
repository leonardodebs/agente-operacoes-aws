# Variaveis de configuracao do projeto.

variable "aws_region" {
  description = "Regiao AWS onde a infra sera provisionada."
  type        = string
  default     = "us-west-2"
}

variable "projeto" {
  description = "Nome do projeto (usado em tags)."
  type        = string
  default     = "agente-operacoes-aws"
}

variable "ambiente" {
  description = "Ambiente logico (usado em tags)."
  type        = string
  default     = "producao"
}

variable "agent_name" {
  description = "Nome do Bedrock Agent."
  type        = string
  default     = "infra-ops-production"
}

variable "foundation_model" {
  description = "Modelo de fundacao do agente. Usamos o inference profile do Claude Haiku 4.5 (o Claude 3 Haiku original foi marcado como Legacy pela Anthropic e bloqueado para novos usuarios)."
  type        = string
  default     = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
}

variable "tools_function_name" {
  description = "Nome da Lambda de ferramentas (action group)."
  type        = string
  default     = "infra-ops-tools"
}

variable "slack_function_name" {
  description = "Nome da Lambda que recebe eventos do Slack."
  type        = string
  default     = "slack-handler"
}

variable "log_retention_days" {
  description = "Retencao dos logs no CloudWatch (dias)."
  type        = number
  default     = 14
}

variable "github_owner" {
  description = "Owner (usuario/org) do repositorio GitHub para o OIDC."
  type        = string
  default     = "leonardodebs"
}

variable "github_repo" {
  description = "Nome do repositorio GitHub para o OIDC."
  type        = string
  default     = "agente-operacoes-aws"
}

variable "create_github_oidc_provider" {
  description = "Se true, cria o OIDC provider do GitHub. Deixe false se ele ja existir na conta."
  type        = bool
  default     = true
}

# agente-operacoes-aws - Projeto capstone (producao).
# Provider, contexto de conta/regiao e empacotamento das Lambdas.

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Projeto   = var.projeto
      Ambiente  = var.ambiente
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# Empacota a Lambda de ferramentas (handler + schema).
data "archive_file" "tools_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/tools"
  output_path = "${path.module}/build/tools.zip"
}

# Empacota a Lambda do Slack. Em CI/CD o zip e regerado com as dependencias
# (slack_sdk) instaladas; localmente o `terraform plan` ainda funciona.
data "archive_file" "slack_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda/slack"
  output_path = "${path.module}/build/slack.zip"
}

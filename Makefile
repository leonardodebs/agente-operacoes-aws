# Atalhos de desenvolvimento do agente-operacoes-aws.
.PHONY: help install test fmt validate plan apply destroy package smoke

help: ## Lista os alvos disponiveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Instala dependencias Python (testes/dev)
	pip install -r requirements.txt

test: ## Roda a suite de testes (mock AWS + Slack)
	python -m pytest tests/ -v

fmt: ## Formata o Terraform
	terraform -chdir=terraform fmt -recursive

validate: ## Valida o Terraform
	terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate

plan: ## Mostra o plano do Terraform
	terraform -chdir=terraform plan

apply: ## Aplica a infraestrutura
	terraform -chdir=terraform apply

destroy: ## Destroi a infraestrutura
	terraform -chdir=terraform destroy

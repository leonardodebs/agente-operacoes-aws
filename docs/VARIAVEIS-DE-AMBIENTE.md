# Variáveis de Ambiente e Configuração — agente-operacoes-aws

Referência de todas as variáveis usadas pelo projeto: ambiente local, runtime
das Lambdas, segredos, variáveis do Terraform e do CI/CD. Use como template ao
configurar um novo ambiente.

> **Regra de ouro:** segredos reais (tokens do Slack) **nunca** vão para `.env`
> versionado, `terraform.tfvars` versionado ou variáveis de ambiente da Lambda.
> Eles vivem no **Secrets Manager**.

---

## 1. Ambiente local (`.env`)

Usado apenas para desenvolvimento/testes locais. Copie de
[../.env.example](../.env.example) para `.env` (o `.env` está no `.gitignore`).

```dotenv
# Região AWS onde a infra é provisionada.
AWS_DEFAULT_REGION=us-west-2

# --- Slack (em produção ficam no Secrets Manager, nunca no código) ---
# Usados apenas para testes locais e para popular o secret na primeira vez.
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret

# --- Bedrock Agent (preenchidos via `terraform output`) ---
BEDROCK_AGENT_ID=
BEDROCK_AGENT_ALIAS_ID=
```

| Variável | Obrigatória | Descrição | Onde obter |
|----------|:-----------:|-----------|------------|
| `AWS_DEFAULT_REGION` | sim | Região dos recursos | — (padrão `us-west-2`) |
| `SLACK_BOT_TOKEN` | local | Token do bot (`xoxb-...`) | Slack → OAuth & Permissions |
| `SLACK_SIGNING_SECRET` | local | Segredo de assinatura | Slack → Basic Information |
| `BEDROCK_AGENT_ID` | local | ID do agente | `terraform output agent_id` |
| `BEDROCK_AGENT_ALIAS_ID` | local | ID do alias `live` | `terraform output agent_alias_id` |

---

## 2. Runtime das Lambdas (definidas pelo Terraform)

Estas **não** são preenchidas à mão — o Terraform as injeta a partir dos
recursos criados. Listadas aqui para referência/diagnóstico.

### 2.1 `slack-handler`
| Variável | Origem (Terraform) | Descrição |
|----------|--------------------|-----------|
| `DEFAULT_REGION` | `var.aws_region` | Região dos clientes boto3 |
| `BEDROCK_AGENT_ID` | `aws_bedrockagent_agent.infra_ops.agent_id` | Agente a invocar |
| `BEDROCK_AGENT_ALIAS_ID` | `aws_bedrockagent_agent_alias.live.agent_alias_id` | Alias estável |
| `HISTORY_TABLE` | `aws_dynamodb_table.history.name` | Tabela de sessões |
| `SLACK_SECRET_ARN` | `aws_secretsmanager_secret.slack.arn` | Secret com os tokens |

### 2.2 `infra-ops-tools`
| Variável | Origem (Terraform) | Descrição |
|----------|--------------------|-----------|
| `DEFAULT_REGION` | `var.aws_region` | Região padrão das consultas AWS |

> `AWS_DEFAULT_REGION` é reservada pela própria Lambda e não pode ser definida
> manualmente; por isso usamos `DEFAULT_REGION`.

---

## 3. Segredo no Secrets Manager (`slack-tokens`)

JSON com os tokens reais do Slack. O Terraform cria apenas um **placeholder**
(`PREENCHER`) e ignora alterações posteriores; o valor real é injetado fora do IaC:

```bash
aws secretsmanager put-secret-value \
  --secret-id slack-tokens \
  --secret-string '{
    "SLACK_BOT_TOKEN": "xoxb-...",
    "SLACK_SIGNING_SECRET": "..."
  }' \
  --region us-west-2
```

| Chave do JSON | Descrição |
|---------------|-----------|
| `SLACK_BOT_TOKEN` | Token usado em `chat.postMessage` |
| `SLACK_SIGNING_SECRET` | Usado para validar a assinatura HMAC das requisições |

---

## 4. Variáveis do Terraform (`terraform.tfvars`)

Copie de [../terraform/terraform.tfvars.example](../terraform/terraform.tfvars.example)
para `terraform/terraform.tfvars` (não versionado).

```hcl
aws_region = "us-west-2"
ambiente   = "producao"

# OIDC do GitHub Actions
github_owner = "leonardodebs"
github_repo  = "agente-operacoes-aws"

# Deixe true na primeira vez; se a conta JÁ tiver o OIDC provider do GitHub,
# defina false para não tentar criá-lo de novo.
create_github_oidc_provider = true
```

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `aws_region` | `us-west-2` | Região de provisionamento |
| `projeto` | `agente-operacoes-aws` | Nome do projeto (tags) |
| `ambiente` | `producao` | Ambiente lógico (tags) |
| `agent_name` | `infra-ops-production` | Nome do Bedrock Agent |
| `foundation_model` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Modelo do agente |
| `tools_function_name` | `infra-ops-tools` | Nome da Lambda de ferramentas |
| `slack_function_name` | `slack-handler` | Nome da Lambda do Slack |
| `log_retention_days` | `14` | Retenção dos logs no CloudWatch |
| `github_owner` | `leonardodebs` | Owner do repositório (OIDC) |
| `github_repo` | `agente-operacoes-aws` | Nome do repositório (OIDC) |
| `create_github_oidc_provider` | `true` | Cria o OIDC provider (false se já existir) |

---

## 5. Configuração do CI/CD (GitHub Actions)

### Secrets do repositório
| Secret | Obrigatório | Descrição |
|--------|:-----------:|-----------|
| `AWS_DEPLOY_ROLE_ARN` | sim | ARN da role assumida via OIDC (`terraform output github_actions_role_arn`). **Não é uma credencial** — apenas o ARN. |

> Não há `AWS_ACCESS_KEY_ID` nem `AWS_SECRET_ACCESS_KEY`. O acesso é via OIDC
> (token de curta duração trocado por credenciais temporárias no STS).

### Variáveis fixas nos workflows
| Variável | Onde | Valor |
|----------|------|-------|
| `AWS_REGION` | `deploy.yml` (`env`) | `us-west-2` |
| `terraform_version` | `ci.yml` / `deploy.yml` | `1.9.5` |
| `python-version` | workflows | `3.12` |

---

## 6. Variáveis usadas nos testes (`tests/conftest.py`)

Definidas automaticamente para mockar a AWS (moto) e permitir o import das
Lambdas sem AWS real. Não precisam de ajuste manual.

| Variável | Valor de teste |
|----------|----------------|
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` | `testing` |
| `AWS_DEFAULT_REGION` / `DEFAULT_REGION` | `us-west-2` |
| `BEDROCK_AGENT_ID` | `AGENT123` |
| `BEDROCK_AGENT_ALIAS_ID` | `ALIAS123` |
| `HISTORY_TABLE` | `conversation-history` |
| `SLACK_SECRET_ARN` | ARN fictício |

---

## 7. Checklist de configuração de um novo ambiente

1. [ ] `terraform/terraform.tfvars` criado a partir do exemplo.
2. [ ] `terraform apply` executado; outputs anotados.
3. [ ] App Slack criado com escopos `chat:write`, `commands`, `app_mentions:read`.
4. [ ] Request URLs (slash command + events) apontando para `slack_function_url`.
5. [ ] Secret `slack-tokens` preenchido com os tokens reais.
6. [ ] Secret `AWS_DEPLOY_ROLE_ARN` configurado no GitHub.
7. [ ] Health check da seção 3 do Runbook executado com sucesso.

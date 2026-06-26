# Runbook Operacional — agente-operacoes-aws

Procedimentos operacionais, diagnóstico e troubleshooting do InfraBot.
Público: quem opera/mantém o serviço (DevOps/SRE).

---

## 1. Referência rápida

| Item | Valor |
|------|-------|
| Região padrão | `us-west-2` |
| Lambda webhook | `slack-handler` |
| Lambda ferramentas | `infra-ops-tools` |
| Bedrock Agent | `infra-ops-production` (alias `live`) |
| Tabela DynamoDB | `conversation-history` |
| Secret | `slack-tokens` |
| Dashboard | `agente-operacoes-aws` |
| Log group webhook | `/aws/lambda/slack-handler` |
| Log group ferramentas | `/aws/lambda/infra-ops-tools` |

Obter os outputs a qualquer momento:
```bash
terraform -chdir=terraform output
```

---

## 2. Deploy

### 2.1 Deploy automático (recomendado)
- **PR** → roda `ci.yml` (checkov, fmt, validate, pytest).
- **Merge na `main`** → roda `deploy.yml` via OIDC: `terraform apply`,
  `update-function-code` nas duas Lambdas e smoke test.

Pré-requisito único no GitHub: secret `AWS_DEPLOY_ROLE_ARN` = output
`github_actions_role_arn`.

### 2.2 Deploy manual (emergência)
```bash
cd terraform
terraform init
terraform apply

# Atualizar só o código das Lambdas (sem mexer na infra):
cd ../lambda/tools && zip -r ../../tools.zip . && cd ../..
aws lambda update-function-code --function-name infra-ops-tools \
  --zip-file fileb://tools.zip --region us-west-2

# A slack-handler precisa do slack_sdk empacotado junto:
pip install slack-sdk==3.31.0 -t lambda/slack/
cd lambda/slack && zip -r ../../slack.zip . && cd ../..
aws lambda update-function-code --function-name slack-handler \
  --zip-file fileb://slack.zip --region us-west-2
```

### 2.3 Rollback
```bash
# Listar versões publicadas da Lambda:
aws lambda list-versions-by-function --function-name slack-handler --region us-west-2
# Reverter código via git e reaplicar:
git revert <commit> && git push    # dispara o deploy novamente
```

---

## 3. Verificação de saúde (health check)

```bash
# 1) A Function URL responde? (sem assinatura → esperado 401)
URL=$(terraform -chdir=terraform output -raw slack_function_url)
curl -s -o /dev/null -w "%{http_code}\n" -X POST "$URL" -d '{}'
# Esperado: 401  (a Lambda está no ar e a validação de assinatura funciona)

# 2) Smoke test direto na Lambda
aws lambda invoke --function-name slack-handler \
  --payload '{"headers":{},"body":"{}"}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 resposta.json && cat resposta.json
# Esperado: statusCode 401

# 3) O agente responde? (sessão de teste)
aws bedrock-agent-runtime invoke-agent \
  --agent-id $(terraform -chdir=terraform output -raw agent_id) \
  --agent-alias-id $(terraform -chdir=terraform output -raw agent_alias_id) \
  --session-id smoke-$(date +%s) \
  --input-text "liste as instâncias EC2" \
  --region us-west-2 /dev/stdout
```

---

## 4. Operações comuns

### 4.1 Atualizar os tokens do Slack
```bash
aws secretsmanager put-secret-value --secret-id slack-tokens \
  --secret-string '{"SLACK_BOT_TOKEN":"xoxb-...","SLACK_SIGNING_SECRET":"..."}' \
  --region us-west-2
```
> A `slack-handler` faz cache dos segredos em memória por container. Após girar
> tokens, force renovação publicando o código de novo ou aguarde o reciclo dos
> containers (alguns minutos).

### 4.2 Inspecionar a sessão de um usuário
```bash
aws dynamodb get-item --table-name conversation-history \
  --key '{"conversation_key":{"S":"U123#C456"}}' --region us-west-2
```

### 4.3 Resetar a conversa de um usuário (perder contexto)
```bash
aws dynamodb delete-item --table-name conversation-history \
  --key '{"conversation_key":{"S":"U123#C456"}}' --region us-west-2
```

### 4.4 Ver logs recentes
```bash
aws logs tail /aws/lambda/slack-handler --since 15m --follow --region us-west-2
aws logs tail /aws/lambda/infra-ops-tools --since 15m --follow --region us-west-2
```

---

## 5. Troubleshooting

### Sintoma: o bot não responde no Slack
1. **Verifique os logs** da `slack-handler` (`aws logs tail ...`).
2. **`assinatura_invalida` nos logs** → o `SLACK_SIGNING_SECRET` no Secrets
   Manager não confere com o do app Slack. Atualize (seção 4.1).
3. **Sem nenhuma invocação** → a Request URL do app Slack está errada. Confira em
   *Slash Commands* e *Event Subscriptions* se aponta para a `slack_function_url`.
4. **`event` chega mas nada é postado** → cheque escopos OAuth do bot
   (`chat:write`). Sem ele, `chat.postMessage` falha com `SlackApiError`.

### Sintoma: "aviso de timeout" no Slack mas a resposta aparece depois
- Esperado quando o Bedrock demora > 3s. O Slack exibe o aviso, mas a mensagem é
  postada via Web API logo em seguida. Para eliminar: implementar ack imediato +
  processamento assíncrono (ver Arquitetura, seção 8).

### Sintoma: resposta duplicada
- O Slack reenvia o evento se não recebe `200` em 3s. O handler **ignora retries**
  via header `X-Slack-Retry-Num`. Se houver duplicidade, confirme que esse trecho
  não foi removido em [lambda/slack/handler.py](../lambda/slack/handler.py).

### Sintoma: agente responde "não encontrei" para tudo
1. Logs da `infra-ops-tools` mostram `ferramenta_falhou`?
   - **`AccessDenied`** → falta permissão IAM de leitura para o serviço. Revise
     [terraform/iam.tf](../terraform/iam.tf) (`tools_readonly`).
   - **`Throttling`** → o retry com backoff deve absorver; se persistir, reduza a
     frequência ou aumente o limite do serviço.
2. **GuardDuty retorna `enabled: false`** → o GuardDuty não está habilitado na
   região; é um estado válido, não um erro.
3. **Custos vazios** → o Cost Explorer leva ~24h para popular dados em contas
   novas e é cobrado por chamada; confirme que está habilitado.

### Sintoma: erro ao invocar o agente (`AccessDeniedException` no Bedrock)
- A role do agente precisa de `InvokeModel` no inference profile **e** no modelo
  base. Se trocou o `foundation_model`, reaplique o Terraform — `recursos_modelo`
  em [terraform/iam.tf](../terraform/iam.tf) recalcula os ARNs.
- Confirme que o modelo Claude Haiku 4.5 está **habilitado** no Bedrock da região.

### Sintoma: deploy falha no GitHub Actions
- **`Could not assume role`** → secret `AWS_DEPLOY_ROLE_ARN` ausente/errado, ou a
  trust policy não cobre a branch/repo. Veja `github_assume` em
  [terraform/oidc.tf](../terraform/oidc.tf).
- **Checkov falha** → há finding HIGH/CRITICAL no Terraform. Corrija ou avalie um
  *skip* justificado.

---

## 6. Monitoramento e alertas

- Abra o **Dashboard** `agente-operacoes-aws` no CloudWatch para invocações,
  erros, latência p50/p99 e throttles.
- Consulta útil (Logs Insights) — ferramentas mais lentas:
  ```
  fields @timestamp, api_path, duracao_ms
  | filter event = "ferramenta_ok"
  | sort duracao_ms desc | limit 20
  ```
- Consulta — erros por tipo:
  ```
  fields @timestamp, api_path, tipo, erro
  | filter event = "ferramenta_falhou"
  | stats count() by tipo
  ```
- **Evolução sugerida:** alarme do CloudWatch em `Errors > 0` (5 min) notificando
  um canal do Slack.

---

## 7. Recuperação de desastres

- **Estado do Terraform:** mantenha backup do `terraform.tfstate` (idealmente em
  backend remoto S3 com versionamento + lock no DynamoDB).
- **DynamoDB:** PITR habilitado — restauração para qualquer ponto dos últimos 35
  dias via console/CLI.
- **Reprovisionar do zero:** `terraform apply` recria toda a infra; depois
  repreencher o secret (seção 4.1) e reconfigurar as URLs no app Slack se a
  Function URL mudar.

---

## 8. Contatos / escalonamento

| Camada | Onde olhar primeiro |
|--------|---------------------|
| Slack não entrega evento | Painel do app em api.slack.com (Event Subscriptions) |
| Webhook/sessão | Logs `slack-handler` + tabela DynamoDB |
| Consulta AWS | Logs `infra-ops-tools` + IAM |
| Raciocínio/idioma do agente | System prompt em [terraform/agent.tf](../terraform/agent.tf) |
| Pipeline | GitHub Actions (`ci.yml` / `deploy.yml`) |

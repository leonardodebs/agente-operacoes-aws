"""Handler do Slack: ponte entre o Slack e o Bedrock Agent.

Fluxo:
  1. Valida a assinatura HMAC da requisicao Slack (seguranca - rejeita falsas).
  2. Trata o desafio de verificacao de URL (url_verification).
  3. Aceita slash command `/infra <pergunta>` e mention `@InfraBot <pergunta>`.
  4. Extrai user_id, channel_id e o texto da pergunta.
  5. Carrega o sessionId da conversa no DynamoDB (chave: user_id + channel_id),
     garantindo continuidade de sessao com o Bedrock Agent.
  6. Invoca o Bedrock Agent (streaming agregado em texto).
  7. Posta a resposta no Slack; ferramentas usadas vao em reply na thread.
  8. Atualiza o DynamoDB com o novo turno.

Esta Lambda e exposta por uma Lambda Function URL (sem API Gateway).
Os segredos (token e signing secret) vem do Secrets Manager, nunca do codigo.
"""
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import uuid

import boto3
from botocore.config import Config
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
REGIAO = os.environ.get("DEFAULT_REGION", "us-west-2")
AGENT_ID = os.environ["BEDROCK_AGENT_ID"]
AGENT_ALIAS_ID = os.environ["BEDROCK_AGENT_ALIAS_ID"]
TABELA_HISTORICO = os.environ["HISTORY_TABLE"]
SECRET_ARN = os.environ["SLACK_SECRET_ARN"]

# Janela maxima (segundos) entre o timestamp do Slack e agora (anti-replay).
JANELA_ASSINATURA = 60 * 5

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_bedrock = boto3.client("bedrock-agent-runtime", region_name=REGIAO,
                        config=Config(read_timeout=60, retries={"max_attempts": 2}))
_dynamo = boto3.resource("dynamodb", region_name=REGIAO)
_tabela = _dynamo.Table(TABELA_HISTORICO)

# Cache em memoria dos segredos (a Lambda reutiliza o container entre invocacoes).
_segredos_cache = None


def log_json(nivel, evento, **campos):
    logger.log(nivel, json.dumps({"event": evento, **campos},
                                 ensure_ascii=False, default=str))


def carregar_segredos():
    """Le SLACK_BOT_TOKEN e SLACK_SIGNING_SECRET do Secrets Manager (com cache)."""
    global _segredos_cache
    if _segredos_cache is None:
        sm = boto3.client("secretsmanager", region_name=REGIAO)
        bruto = sm.get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        _segredos_cache = json.loads(bruto)
    return _segredos_cache


# ---------------------------------------------------------------------------
# Seguranca - validacao de assinatura do Slack
# ---------------------------------------------------------------------------
def assinatura_valida(headers, corpo_bruto, signing_secret):
    """Valida a assinatura `v0` do Slack via HMAC-SHA256.

    https://api.slack.com/authentication/verifying-requests-from-slack
    Rejeita: timestamp ausente/antigo (replay) ou assinatura divergente.
    """
    timestamp = headers.get("x-slack-request-timestamp")
    assinatura = headers.get("x-slack-signature")
    if not timestamp or not assinatura:
        return False

    # Protecao contra replay: descarta requisicoes antigas.
    try:
        if abs(time.time() - int(timestamp)) > JANELA_ASSINATURA:
            return False
    except ValueError:
        return False

    base = f"v0:{timestamp}:{corpo_bruto}".encode("utf-8")
    esperado = "v0=" + hmac.new(
        signing_secret.encode("utf-8"), base, hashlib.sha256
    ).hexdigest()

    # Comparacao em tempo constante evita timing attacks.
    return hmac.compare_digest(esperado, assinatura)


# ---------------------------------------------------------------------------
# Sessao no DynamoDB (continuidade da conversa por usuario+canal)
# ---------------------------------------------------------------------------
def obter_session_id(user_id, channel_id):
    """Recupera (ou cria) o sessionId do Bedrock para o par usuario+canal."""
    chave = f"{user_id}#{channel_id}"
    resp = _tabela.get_item(Key={"conversation_key": chave})
    item = resp.get("Item")
    if item and item.get("session_id"):
        return chave, item["session_id"]
    # Nova conversa: gera um sessionId estavel.
    return chave, f"sess-{uuid.uuid4().hex[:16]}"


def salvar_turno(chave, session_id, pergunta, resposta):
    """Persiste o ultimo turno e renova o TTL (30 dias) da conversa."""
    agora = int(time.time())
    _tabela.put_item(Item={
        "conversation_key": chave,
        "session_id": session_id,
        "last_question": pergunta,
        "last_answer": resposta[:4000],
        "updated_at": agora,
        "ttl": agora + 60 * 60 * 24 * 30,
    })


# ---------------------------------------------------------------------------
# Bedrock Agent
# ---------------------------------------------------------------------------
def invocar_agente(session_id, pergunta):
    """Invoca o Bedrock Agent e agrega o stream em (texto, ferramentas_usadas)."""
    resp = _bedrock.invoke_agent(
        agentId=AGENT_ID,
        agentAliasId=AGENT_ALIAS_ID,
        sessionId=session_id,
        inputText=pergunta,
        enableTrace=True,
    )

    partes = []
    ferramentas = []
    for evento in resp["completion"]:
        if "chunk" in evento:
            partes.append(evento["chunk"]["bytes"].decode("utf-8"))
        elif "trace" in evento:
            _coletar_ferramentas(evento["trace"], ferramentas)

    texto = "".join(partes).strip() or "Nao consegui gerar uma resposta."
    # Remove duplicatas preservando ordem.
    ferramentas_unicas = list(dict.fromkeys(ferramentas))
    return texto, ferramentas_unicas


def _coletar_ferramentas(trace, acumulador):
    """Extrai do trace os nomes das ferramentas (apiPath) que o agente invocou."""
    orchestration = trace.get("trace", {}).get("orchestrationTrace", {})
    invocacao = orchestration.get("invocationInput", {})
    action = invocacao.get("actionGroupInvocationInput", {})
    api_path = action.get("apiPath")
    if api_path:
        acumulador.append(api_path.lstrip("/"))


# ---------------------------------------------------------------------------
# Slack - postagem de mensagens
# ---------------------------------------------------------------------------
def postar_resposta(client, channel, thread_ts, texto, ferramentas):
    """Posta a resposta principal e, se houver, as ferramentas usadas na thread."""
    principal = client.chat_postMessage(channel=channel, text=texto,
                                        thread_ts=thread_ts)
    ts_principal = principal["ts"]
    if ferramentas:
        nomes = ", ".join(f"`{f}`" for f in ferramentas)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts or ts_principal,
            text=f":wrench: *Ferramentas consultadas:* {nomes}",
        )


def postar_erro(client, channel, thread_ts, detalhe):
    client.chat_postMessage(
        channel=channel, thread_ts=thread_ts,
        text=f":warning: Nao consegui responder agora. ({detalhe})",
    )


# ---------------------------------------------------------------------------
# Processamento dos eventos do Slack
# ---------------------------------------------------------------------------
def _limpar_mention(texto):
    """Remove o prefixo `<@U123...>` de uma mention, deixando so a pergunta."""
    partes = texto.split(">", 1)
    return partes[1].strip() if len(partes) == 2 else texto.strip()


def processar_pergunta(client, user_id, channel_id, thread_ts, pergunta):
    """Orquestra: sessao -> agente -> postagem -> persistencia."""
    if not pergunta:
        postar_erro(client, channel_id, thread_ts, "pergunta vazia")
        return

    chave, session_id = obter_session_id(user_id, channel_id)
    try:
        texto, ferramentas = invocar_agente(session_id, pergunta)
    except Exception as erro:  # noqa: BLE001
        log_json(logging.ERROR, "agente_falhou", erro=str(erro),
                 tipo=type(erro).__name__)
        postar_erro(client, channel_id, thread_ts, type(erro).__name__)
        return

    postar_resposta(client, channel_id, thread_ts, texto, ferramentas)
    salvar_turno(chave, session_id, pergunta, texto)


def tratar_slash_command(client, corpo_bruto):
    """Slash command `/infra <pergunta>` chega como form-urlencoded."""
    dados = urllib.parse.parse_qs(corpo_bruto)
    user_id = dados.get("user_id", [""])[0]
    channel_id = dados.get("channel_id", [""])[0]
    pergunta = dados.get("text", [""])[0].strip()
    log_json(logging.INFO, "slash_command", user=user_id, channel=channel_id)
    processar_pergunta(client, user_id, channel_id, None, pergunta)


def tratar_evento(client, evento):
    """Evento da Events API (ex.: app_mention)."""
    tipo = evento.get("type")
    # Ignora mensagens do proprio bot para evitar loop.
    if evento.get("bot_id"):
        return
    if tipo == "app_mention":
        user_id = evento.get("user", "")
        channel_id = evento.get("channel", "")
        thread_ts = evento.get("thread_ts") or evento.get("ts")
        pergunta = _limpar_mention(evento.get("text", ""))
        log_json(logging.INFO, "app_mention", user=user_id, channel=channel_id)
        processar_pergunta(client, user_id, channel_id, thread_ts, pergunta)


# ---------------------------------------------------------------------------
# Entrada da Lambda (Function URL)
# ---------------------------------------------------------------------------
def _resposta(status, corpo=""):
    return {"statusCode": status, "body": corpo}


def lambda_handler(event, context):
    """Ponto de entrada da Lambda Function URL."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    corpo_bruto = event.get("body") or ""

    segredos = carregar_segredos()

    # 1) Seguranca: valida a assinatura ANTES de qualquer processamento.
    if not assinatura_valida(headers, corpo_bruto, segredos["SLACK_SIGNING_SECRET"]):
        log_json(logging.WARNING, "assinatura_invalida")
        return _resposta(401, "assinatura invalida")

    content_type = headers.get("content-type", "")

    # 2) Slash command (application/x-www-form-urlencoded).
    if "application/x-www-form-urlencoded" in content_type:
        client = WebClient(token=segredos["SLACK_BOT_TOKEN"])
        try:
            tratar_slash_command(client, corpo_bruto)
        except SlackApiError as erro:
            log_json(logging.ERROR, "slack_api_erro", erro=str(erro))
        # Ack imediato (o Slack mostra a resposta postada via chat.postMessage).
        return _resposta(200, "")

    # 3) Events API (application/json).
    try:
        payload = json.loads(corpo_bruto or "{}")
    except json.JSONDecodeError:
        return _resposta(400, "json invalido")

    # 3a) Desafio de verificacao de URL (uma unica vez, ao configurar o app).
    if payload.get("type") == "url_verification":
        return _resposta(200, payload.get("challenge", ""))

    # 3b) O Slack re-tenta em 3s; ignoramos retries para nao duplicar respostas.
    if headers.get("x-slack-retry-num"):
        log_json(logging.INFO, "retry_ignorado",
                 num=headers.get("x-slack-retry-num"))
        return _resposta(200, "")

    if payload.get("type") == "event_callback":
        client = WebClient(token=segredos["SLACK_BOT_TOKEN"])
        try:
            tratar_evento(client, payload.get("event", {}))
        except SlackApiError as erro:
            log_json(logging.ERROR, "slack_api_erro", erro=str(erro))
        return _resposta(200, "")

    return _resposta(200, "")

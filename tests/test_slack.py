"""Testes do fluxo do slack-handler com Slack + Bedrock + DynamoDB mockados.

Cobre:
  - desafio url_verification
  - rejeicao de requisicao com assinatura invalida (401)
  - fluxo completo de um slash command: agente -> postagem no Slack -> persistencia
  - parsing da mention e do slash command
"""
import hashlib
import hmac
import json
import sys
import time

import pytest

slack = sys.modules.get("slack_handler_module")
if slack is None:  # pragma: no cover
    pytest.skip("slack_sdk indisponivel; pulando testes do slack handler",
                allow_module_level=True)

SIGNING_SECRET = "signing-secret-teste"
BOT_TOKEN = "xoxb-fake"


@pytest.fixture(autouse=True)
def segredos_e_clientes(monkeypatch):
    """Injeta segredos falsos e remove dependencia de rede em todos os testes."""
    monkeypatch.setattr(slack, "carregar_segredos", lambda: {
        "SLACK_BOT_TOKEN": BOT_TOKEN,
        "SLACK_SIGNING_SECRET": SIGNING_SECRET,
    })


def _assinar(corpo):
    ts = str(int(time.time()))
    base = f"v0:{ts}:{corpo}".encode("utf-8")
    sig = "v0=" + hmac.new(SIGNING_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return {"x-slack-request-timestamp": ts, "x-slack-signature": sig}


def test_url_verification_retorna_challenge():
    corpo = json.dumps({"type": "url_verification", "challenge": "abc123"})
    evento = {
        "headers": {**_assinar(corpo), "content-type": "application/json"},
        "body": corpo,
    }
    resp = slack.lambda_handler(evento, None)
    assert resp["statusCode"] == 200
    assert resp["body"] == "abc123"


def test_assinatura_invalida_retorna_401():
    corpo = json.dumps({"type": "event_callback"})
    evento = {
        "headers": {"content-type": "application/json",
                    "x-slack-request-timestamp": str(int(time.time())),
                    "x-slack-signature": "v0=errado"},
        "body": corpo,
    }
    resp = slack.lambda_handler(evento, None)
    assert resp["statusCode"] == 401


def test_retry_do_slack_e_ignorado():
    corpo = json.dumps({"type": "event_callback", "event": {"type": "app_mention"}})
    headers = {**_assinar(corpo), "content-type": "application/json",
               "x-slack-retry-num": "1"}
    resp = slack.lambda_handler({"headers": headers, "body": corpo}, None)
    assert resp["statusCode"] == 200


def test_slash_command_fluxo_completo(monkeypatch):
    # Mock do agente: retorna texto + ferramentas usadas.
    monkeypatch.setattr(slack, "invocar_agente",
                        lambda sid, q: ("2 instancias rodando.", ["list-ec2"]))
    # Mock da sessao e persistencia (sem DynamoDB real).
    monkeypatch.setattr(slack, "obter_session_id",
                        lambda u, c: ("U1#C1", "sess-xyz"))
    salvos = {}
    monkeypatch.setattr(slack, "salvar_turno",
                        lambda chave, sid, p, r: salvos.update(
                            {"chave": chave, "sid": sid, "p": p, "r": r}))

    # Captura as mensagens postadas no Slack.
    postadas = []

    class FakeWeb:
        def __init__(self, token=None):
            assert token == BOT_TOKEN

        def chat_postMessage(self, **kwargs):
            postadas.append(kwargs)
            return {"ts": "111.222"}

    monkeypatch.setattr(slack, "WebClient", FakeWeb)

    corpo = "user_id=U1&channel_id=C1&text=quais+instancias+EC2"
    headers = {**_assinar(corpo),
               "content-type": "application/x-www-form-urlencoded"}
    resp = slack.lambda_handler({"headers": headers, "body": corpo}, None)

    assert resp["statusCode"] == 200
    # Mensagem principal + reply com as ferramentas.
    assert len(postadas) == 2
    assert postadas[0]["text"] == "2 instancias rodando."
    assert "list-ec2" in postadas[1]["text"]
    # Turno persistido.
    assert salvos["sid"] == "sess-xyz"
    assert salvos["r"] == "2 instancias rodando."


def test_limpar_mention_remove_prefixo():
    assert slack._limpar_mention("<@U123> tem alarme?") == "tem alarme?"


def test_app_mention_invoca_processamento(monkeypatch):
    chamado = {}
    monkeypatch.setattr(slack, "processar_pergunta",
                        lambda client, u, c, t, p: chamado.update(
                            {"user": u, "channel": c, "pergunta": p, "thread": t}))

    class FakeWeb:
        def __init__(self, token=None):
            pass

    monkeypatch.setattr(slack, "WebClient", FakeWeb)

    corpo = json.dumps({
        "type": "event_callback",
        "event": {"type": "app_mention", "user": "U9", "channel": "C9",
                  "ts": "1.2", "text": "<@UBOT> qual o custo?"},
    })
    headers = {**_assinar(corpo), "content-type": "application/json"}
    resp = slack.lambda_handler({"headers": headers, "body": corpo}, None)

    assert resp["statusCode"] == 200
    assert chamado["pergunta"] == "qual o custo?"
    assert chamado["user"] == "U9"

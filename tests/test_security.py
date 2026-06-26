"""Testes de seguranca: validacao da assinatura HMAC do Slack.

Garante que requisicoes invalidas (sem assinatura, assinatura errada, replay
antigo) sejam REJEITADAS, e que uma assinatura legitima seja aceita.
"""
import hashlib
import hmac
import sys
import time

import pytest

# Carregado pelo conftest sob nome distinto; pula se slack_sdk nao estiver instalado.
slack = sys.modules.get("slack_handler_module")
if slack is None:  # pragma: no cover
    pytest.skip("slack_sdk indisponivel; pulando testes do slack handler",
                allow_module_level=True)


SIGNING_SECRET = "8f742231b10e8888abcd99yyyzzz85a5"


def assinar(corpo, timestamp, secret=SIGNING_SECRET):
    """Replica a assinatura v0 do Slack para gerar um header valido nos testes."""
    base = f"v0:{timestamp}:{corpo}".encode("utf-8")
    return "v0=" + hmac.new(secret.encode("utf-8"), base, hashlib.sha256).hexdigest()


def test_assinatura_valida_aceita():
    corpo = "token=abc&text=oi"
    ts = str(int(time.time()))
    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": assinar(corpo, ts),
    }
    assert slack.assinatura_valida(headers, corpo, SIGNING_SECRET) is True


def test_assinatura_errada_rejeitada():
    corpo = "token=abc&text=oi"
    ts = str(int(time.time()))
    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": "v0=deadbeef",
    }
    assert slack.assinatura_valida(headers, corpo, SIGNING_SECRET) is False


def test_assinatura_ausente_rejeitada():
    assert slack.assinatura_valida({}, "corpo", SIGNING_SECRET) is False


def test_replay_antigo_rejeitado():
    corpo = "token=abc"
    ts_antigo = str(int(time.time()) - 60 * 10)  # 10 min atras
    headers = {
        "x-slack-request-timestamp": ts_antigo,
        "x-slack-signature": assinar(corpo, ts_antigo),
    }
    assert slack.assinatura_valida(headers, corpo, SIGNING_SECRET) is False


def test_secret_diferente_rejeitado():
    corpo = "token=abc"
    ts = str(int(time.time()))
    headers = {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": assinar(corpo, ts, secret="outro-secret"),
    }
    assert slack.assinatura_valida(headers, corpo, SIGNING_SECRET) is False

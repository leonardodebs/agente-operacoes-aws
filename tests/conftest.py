"""Configuracao compartilhada dos testes.

As duas Lambdas tem arquivos chamados `handler.py`. Para importar ambas sem
colisao, carregamos cada uma sob um nome de modulo distinto via importlib:
  - tools_handler          -> lambda/tools/handler.py
  - slack_handler_module   -> lambda/slack/handler.py
"""
import importlib.util
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Envs falsas para AWS (moto) e para o import do slack handler (le envs no topo).
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("DEFAULT_REGION", "us-west-2")
os.environ.setdefault("BEDROCK_AGENT_ID", "AGENT123")
os.environ.setdefault("BEDROCK_AGENT_ALIAS_ID", "ALIAS123")
os.environ.setdefault("HISTORY_TABLE", "conversation-history")
os.environ.setdefault(
    "SLACK_SECRET_ARN",
    "arn:aws:secretsmanager:us-west-2:123456789012:secret:slack-tokens",
)


def _carregar(nome_modulo, caminho_relativo):
    """Carrega um arquivo .py sob um nome de modulo explicito."""
    caminho = os.path.join(RAIZ, caminho_relativo)
    spec = importlib.util.spec_from_file_location(nome_modulo, caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome_modulo] = modulo
    spec.loader.exec_module(modulo)
    return modulo


# A Lambda de ferramentas nao tem dependencias externas e carrega sempre.
_carregar("tools_handler", "lambda/tools/handler.py")

# A Lambda do Slack depende de slack_sdk; se ausente, deixamos os testes que a
# usam serem pulados (skip) em vez de quebrar a coleta inteira.
try:
    _carregar("slack_handler_module", "lambda/slack/handler.py")
except ModuleNotFoundError:  # pragma: no cover
    pass

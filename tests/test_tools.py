"""Testes das ferramentas (lambda/tools/handler.py) com AWS mockada via moto.

Cada teste cria recursos falsos com moto e verifica que a ferramenta retorna
o schema esperado. As ferramentas sem suporte no moto (Cost Explorer, GuardDuty)
sao testadas com stub/mock direto do cliente boto3.
"""
import json
from unittest.mock import MagicMock

import boto3
from moto import mock_aws

import tools_handler as tools  # carregado pelo conftest


# ---------------------------------------------------------------------------
# list_ec2 / get_ec2_details
# ---------------------------------------------------------------------------
@mock_aws
def test_list_ec2_retorna_schema():
    ec2 = boto3.resource("ec2", region_name="us-west-2")
    ec2.create_instances(
        ImageId="ami-12345678", MinCount=2, MaxCount=2, InstanceType="t3.micro"
    )

    resultado = tools.list_ec2({"region": "us-west-2"})

    assert resultado["region"] == "us-west-2"
    assert resultado["count"] == 2
    assert len(resultado["instances"]) == 2
    inst = resultado["instances"][0]
    for campo in ("instance_id", "instance_type", "state", "launch_time"):
        assert campo in inst


@mock_aws
def test_list_ec2_filtra_por_estado():
    ec2 = boto3.resource("ec2", region_name="us-west-2")
    instancias = ec2.create_instances(
        ImageId="ami-12345678", MinCount=1, MaxCount=1, InstanceType="t3.micro"
    )
    instancias[0].stop()

    rodando = tools.list_ec2({"state": "running"})
    parado = tools.list_ec2({"state": "stopped"})

    assert rodando["count"] == 0
    assert parado["count"] == 1


@mock_aws
def test_get_ec2_details_sem_id_retorna_erro():
    resultado = tools.get_ec2_details({})
    assert "error" in resultado


# ---------------------------------------------------------------------------
# list_rds
# ---------------------------------------------------------------------------
@mock_aws
def test_list_rds_retorna_schema():
    rds = boto3.client("rds", region_name="us-west-2")
    rds.create_db_instance(
        DBInstanceIdentifier="db-teste",
        Engine="postgres",
        DBInstanceClass="db.t3.micro",
        AllocatedStorage=20,
        MasterUsername="admin",
        MasterUserPassword="senhaSuperSecreta1",
    )

    resultado = tools.list_rds({})

    assert resultado["count"] == 1
    db = resultado["databases"][0]
    assert db["db_id"] == "db-teste"
    assert db["engine"] == "postgres"


# ---------------------------------------------------------------------------
# get_cloudwatch_alarms
# ---------------------------------------------------------------------------
@mock_aws
def test_get_cloudwatch_alarms_schema():
    cw = boto3.client("cloudwatch", region_name="us-west-2")
    cw.put_metric_alarm(
        AlarmName="cpu-alta",
        MetricName="CPUUtilization",
        Namespace="AWS/EC2",
        Statistic="Average",
        Period=300,
        EvaluationPeriods=1,
        Threshold=80.0,
        ComparisonOperator="GreaterThanThreshold",
    )
    resultado = tools.get_cloudwatch_alarms({"state": "INSUFFICIENT_DATA"})
    assert "count" in resultado and "alarms" in resultado


# ---------------------------------------------------------------------------
# list_s3_buckets_summary
# ---------------------------------------------------------------------------
@mock_aws
def test_list_s3_buckets_summary_schema():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="meu-bucket-teste")

    resultado = tools.list_s3_buckets_summary({})

    assert resultado["count"] >= 1
    nomes = [b["name"] for b in resultado["buckets"]]
    assert "meu-bucket-teste" in nomes
    assert all("region" in b for b in resultado["buckets"])


# ---------------------------------------------------------------------------
# get_cost_summary (Cost Explorer - mock direto do cliente)
# ---------------------------------------------------------------------------
def test_get_cost_summary_agrega_por_servico(monkeypatch):
    fake_ce = MagicMock()
    fake_ce.get_cost_and_usage.return_value = {
        "ResultsByTime": [
            {"Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "10.0", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "2.5", "Unit": "USD"}}},
            ]},
            {"Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "5.0", "Unit": "USD"}}},
            ]},
        ]
    }
    monkeypatch.setattr(tools, "cliente", lambda servico, regiao=None: fake_ce)

    resultado = tools.get_cost_summary({"days": 7})

    assert resultado["currency"] == "USD"
    assert resultado["total_cost"] == 17.5
    # EC2 (15.0) deve vir antes de S3 (2.5) na ordenacao decrescente.
    assert resultado["by_service"][0]["service"] == "Amazon EC2"
    assert resultado["by_service"][0]["cost"] == 15.0
    assert resultado["period"]["days"] == 7


# ---------------------------------------------------------------------------
# check_guardduty_findings (mock direto do cliente)
# ---------------------------------------------------------------------------
def test_guardduty_sem_detector_retorna_disabled(monkeypatch):
    fake_gd = MagicMock()
    fake_gd.list_detectors.return_value = {"DetectorIds": []}
    monkeypatch.setattr(tools, "cliente", lambda servico, regiao=None: fake_gd)

    resultado = tools.check_guardduty_findings({})

    assert resultado["enabled"] is False
    assert resultado["count"] == 0


def test_guardduty_classifica_severidade(monkeypatch):
    fake_gd = MagicMock()
    fake_gd.list_detectors.return_value = {"DetectorIds": ["det-1"]}
    paginador = MagicMock()
    paginador.paginate.return_value = [{"FindingIds": ["f1", "f2"]}]
    fake_gd.get_paginator.return_value = paginador
    fake_gd.get_findings.return_value = {"Findings": [
        {"Id": "f1", "Type": "Recon", "Severity": 8.0, "Title": "Acesso suspeito"},
        {"Id": "f2", "Type": "Backdoor", "Severity": 5.0, "Title": "C2"},
    ]}
    monkeypatch.setattr(tools, "cliente", lambda servico, regiao=None: fake_gd)

    resultado = tools.check_guardduty_findings({})

    assert resultado["enabled"] is True
    assert resultado["count"] == 2
    # Ordenado por severidade decrescente; o primeiro deve ser HIGH.
    assert resultado["findings"][0]["severity_label"] == "HIGH"
    assert resultado["findings"][1]["severity_label"] == "MEDIUM"


# ---------------------------------------------------------------------------
# Roteamento e envelope
# ---------------------------------------------------------------------------
@mock_aws
def test_lambda_handler_envelope_valido():
    evento = {
        "actionGroup": "aws-infrastructure-tools",
        "apiPath": "/list-ec2",
        "httpMethod": "POST",
        "parameters": [{"name": "region", "value": "us-west-2"}],
    }
    resp = tools.lambda_handler(evento, None)

    assert resp["messageVersion"] == "1.0"
    corpo = resp["response"]["responseBody"]["application/json"]["body"]
    dados = json.loads(corpo)  # precisa ser JSON valido
    assert "instances" in dados
    assert resp["response"]["httpStatusCode"] == 200


def test_lambda_handler_apipath_desconhecido():
    resp = tools.lambda_handler({"apiPath": "/inexistente"}, None)
    assert resp["response"]["httpStatusCode"] == 404


def test_extrair_parametros_junta_body_e_parameters():
    evento = {
        "parameters": [{"name": "region", "value": "us-east-1"}],
        "requestBody": {"content": {"application/json": {"properties": [
            {"name": "state", "value": "running"}
        ]}}},
    }
    params = tools.extrair_parametros(evento)
    assert params == {"region": "us-east-1", "state": "running"}

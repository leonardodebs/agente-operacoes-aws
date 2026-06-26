"""Ferramentas SOMENTE LEITURA da infraestrutura AWS para o Bedrock Agent.

Esta e a versao de PRODUCAO das ferramentas do Lab 2, expandida com:
  - get_cost_summary       -> custo dos ultimos 7 dias via Cost Explorer
  - check_guardduty_findings -> achados do GuardDuty com severidade >= MEDIUM
  - list_s3_buckets_summary  -> resumo de buckets S3

Caracteristicas de producao:
  - Logging estruturado em JSON (CloudWatch Logs Insights friendly).
  - Retry com backoff exponencial para chamadas boto3 (erros transitorios).
  - Tratamento de erro por ferramenta: o agente sempre recebe um envelope valido.
  - Estritamente read-only: nenhuma acao de escrita/delete e usada ou permitida.

O Bedrock Agent envia um evento com `apiPath`; cada path mapeia uma ferramenta.
"""
import datetime
import functools
import json
import logging
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Configuracao e logging estruturado
# ---------------------------------------------------------------------------
REGIAO_PADRAO = os.environ.get("DEFAULT_REGION", "us-west-2")

# Erros transitorios que valem a pena re-tentar.
ERROS_RETENTAVEIS = {"Throttling", "ThrottlingException", "RequestLimitExceeded",
                     "TooManyRequestsException", "ServiceUnavailable"}

# Config boto3 com retry adaptativo nativo, alem do nosso retry explicito.
BOTO_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def log_json(nivel, evento, **campos):
    """Emite um log em JSON para facilitar buscas no CloudWatch Logs Insights."""
    registro = {"event": evento, **campos}
    logger.log(nivel, json.dumps(registro, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Helpers de clientes, retry e serializacao
# ---------------------------------------------------------------------------
def cliente(servico, regiao=None):
    """Cria um cliente boto3 na regiao informada (ou na padrao)."""
    return boto3.client(servico, region_name=regiao or REGIAO_PADRAO, config=BOTO_CONFIG)


def com_retry(tentativas=3, base=0.5):
    """Decorator: re-tenta a chamada em erros transitorios com backoff exponencial."""
    def decorador(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ultimo_erro = None
            for tentativa in range(1, tentativas + 1):
                try:
                    return func(*args, **kwargs)
                except ClientError as erro:
                    codigo = erro.response.get("Error", {}).get("Code", "")
                    ultimo_erro = erro
                    if codigo not in ERROS_RETENTAVEIS or tentativa == tentativas:
                        raise
                    espera = base * (2 ** (tentativa - 1))
                    log_json(logging.WARNING, "retry",
                             func=func.__name__, tentativa=tentativa,
                             codigo=codigo, espera_s=espera)
                    time.sleep(espera)
            raise ultimo_erro
        return wrapper
    return decorador


def serializar(obj):
    """Converte datetimes em ISO 8601 para virar JSON."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    return str(obj)


def tag_nome(tags):
    """Extrai a tag Name de uma lista de tags EC2 (ou None)."""
    for t in tags or []:
        if t.get("Key") == "Name":
            return t.get("Value")
    return None


# ---------------------------------------------------------------------------
# Ferramenta 1 - list_ec2
# ---------------------------------------------------------------------------
@com_retry()
def list_ec2(params):
    regiao = params.get("region") or REGIAO_PADRAO
    estado = (params.get("state") or "all").lower()

    filtros = []
    if estado in ("running", "stopped"):
        filtros.append({"Name": "instance-state-name", "Values": [estado]})

    ec2 = cliente("ec2", regiao)
    paginador = ec2.get_paginator("describe_instances")
    instancias = []
    for pagina in paginador.paginate(Filters=filtros):
        for reserva in pagina["Reservations"]:
            for inst in reserva["Instances"]:
                instancias.append({
                    "instance_id": inst["InstanceId"],
                    "instance_type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "name_tag": tag_nome(inst.get("Tags")),
                    "launch_time": serializar(inst.get("LaunchTime")),
                    "private_ip": inst.get("PrivateIpAddress"),
                })
    return {"region": regiao, "count": len(instancias), "instances": instancias}


# ---------------------------------------------------------------------------
# Ferramenta 2 - get_ec2_details
# ---------------------------------------------------------------------------
@com_retry()
def get_ec2_details(params):
    instance_id = params.get("instance_id")
    if not instance_id:
        return {"error": "Parametro obrigatorio 'instance_id' nao informado."}

    regiao = params.get("region") or REGIAO_PADRAO
    ec2 = cliente("ec2", regiao)
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    reservas = resp["Reservations"]
    if not reservas:
        return {"error": f"Instancia {instance_id} nao encontrada."}

    inst = reservas[0]["Instances"][0]
    detalhes = {
        "instance_id": inst["InstanceId"],
        "instance_type": inst["InstanceType"],
        "state": inst["State"]["Name"],
        "name_tag": tag_nome(inst.get("Tags")),
        "launch_time": serializar(inst.get("LaunchTime")),
        "private_ip": inst.get("PrivateIpAddress"),
        "public_ip": inst.get("PublicIpAddress"),
        "availability_zone": inst.get("Placement", {}).get("AvailabilityZone"),
        "vpc_id": inst.get("VpcId"),
        "subnet_id": inst.get("SubnetId"),
        "image_id": inst.get("ImageId"),
    }
    detalhes["cpu_last_1h"] = _metricas_cpu(instance_id, regiao)
    return detalhes


@com_retry()
def _metricas_cpu(instance_id, regiao):
    """Media e maximo de CPU (%) na ultima hora via CloudWatch."""
    cw = cliente("cloudwatch", regiao)
    fim = datetime.datetime.now(datetime.timezone.utc)
    inicio = fim - datetime.timedelta(hours=1)
    resp = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=inicio,
        EndTime=fim,
        Period=300,
        Statistics=["Average", "Maximum"],
    )
    pontos = resp.get("Datapoints", [])
    if not pontos:
        return {"avg": None, "max": None, "datapoints": 0}
    return {
        "avg": round(sum(p["Average"] for p in pontos) / len(pontos), 2),
        "max": round(max(p["Maximum"] for p in pontos), 2),
        "datapoints": len(pontos),
        "unit": "Percent",
    }


# ---------------------------------------------------------------------------
# Ferramenta 3 - list_rds
# ---------------------------------------------------------------------------
@com_retry()
def list_rds(params):
    regiao = params.get("region") or REGIAO_PADRAO
    rds = cliente("rds", regiao)
    paginador = rds.get_paginator("describe_db_instances")
    bancos = []
    for pagina in paginador.paginate():
        for db in pagina["DBInstances"]:
            endpoint = db.get("Endpoint") or {}
            bancos.append({
                "db_id": db["DBInstanceIdentifier"],
                "engine": db.get("Engine"),
                "status": db.get("DBInstanceStatus"),
                "instance_class": db.get("DBInstanceClass"),
                "multi_az": db.get("MultiAZ"),
                "endpoint": endpoint.get("Address"),
            })
    return {"region": regiao, "count": len(bancos), "databases": bancos}


# ---------------------------------------------------------------------------
# Ferramenta 4 - check_alb_health
# ---------------------------------------------------------------------------
@com_retry()
def check_alb_health(params):
    arn = params.get("load_balancer_arn")
    nome = params.get("name")
    regiao = params.get("region") or REGIAO_PADRAO
    if not arn and not nome:
        return {"error": "Informe 'load_balancer_arn' ou 'name'."}

    elb = cliente("elbv2", regiao)
    if not arn:
        lbs = elb.describe_load_balancers(Names=[nome])["LoadBalancers"]
        if not lbs:
            return {"error": f"Load balancer '{nome}' nao encontrado."}
        arn = lbs[0]["LoadBalancerArn"]

    grupos = elb.describe_target_groups(LoadBalancerArn=arn)["TargetGroups"]
    resultado = []
    for tg in grupos:
        saude = elb.describe_target_health(
            TargetGroupArn=tg["TargetGroupArn"]
        )["TargetHealthDescriptions"]
        alvos = []
        for alvo in saude:
            estado = alvo["TargetHealth"]
            alvos.append({
                "target_id": alvo["Target"]["Id"],
                "health_status": estado["State"],
                "reason_if_unhealthy": estado.get("Reason"),
                "description": estado.get("Description"),
            })
        resultado.append({
            "target_group_name": tg["TargetGroupName"],
            "protocol": tg.get("Protocol"),
            "port": tg.get("Port"),
            "targets": alvos,
        })
    return {"load_balancer_arn": arn, "target_groups": resultado}


# ---------------------------------------------------------------------------
# Ferramenta 5 - get_cloudwatch_alarms
# ---------------------------------------------------------------------------
@com_retry()
def get_cloudwatch_alarms(params):
    estado = (params.get("state") or "ALARM").upper()
    regiao = params.get("region") or REGIAO_PADRAO
    cw = cliente("cloudwatch", regiao)

    resp = cw.describe_alarms(StateValue=estado, MaxRecords=100)
    alarmes = []
    for al in resp.get("MetricAlarms", []):
        alarmes.append({
            "alarm_name": al["AlarmName"],
            "state": al["StateValue"],
            "reason": al.get("StateReason"),
            "last_updated": serializar(al.get("StateUpdatedTimestamp")),
            "metric": al.get("MetricName"),
            "namespace": al.get("Namespace"),
        })
    return {"state_filter": estado, "count": len(alarmes), "alarms": alarmes}


# ---------------------------------------------------------------------------
# Ferramenta 6 - list_ecs_services
# ---------------------------------------------------------------------------
@com_retry()
def list_ecs_services(params):
    regiao = params.get("region") or REGIAO_PADRAO
    ecs = cliente("ecs", regiao)

    cluster = params.get("cluster_name")
    clusters = [cluster] if cluster else ecs.list_clusters()["clusterArns"]

    servicos = []
    for cl in clusters:
        arns = ecs.list_services(cluster=cl, maxResults=100)["serviceArns"]
        if not arns:
            continue
        # describe_services aceita no maximo 10 servicos por chamada.
        for i in range(0, len(arns), 10):
            lote = ecs.describe_services(cluster=cl, services=arns[i:i + 10])
            for sv in lote["services"]:
                servicos.append({
                    "cluster": cl.split("/")[-1],
                    "service_name": sv["serviceName"],
                    "desired_count": sv["desiredCount"],
                    "running_count": sv["runningCount"],
                    "pending_count": sv["pendingCount"],
                    "status": sv["status"],
                })
    return {"count": len(servicos), "services": servicos}


# ---------------------------------------------------------------------------
# Ferramenta 7 - get_cost_summary (NOVA) - Cost Explorer, ultimos 7 dias
# ---------------------------------------------------------------------------
@com_retry()
def get_cost_summary(params):
    """Custo (UnblendedCost) dos ultimos N dias agrupado por servico.

    Cost Explorer e um endpoint GLOBAL atendido em us-east-1, independente da
    regiao dos recursos. O periodo e [hoje-N, hoje) com granularidade diaria.
    """
    dias = int(params.get("days") or 7)
    ce = cliente("ce", "us-east-1")

    hoje = datetime.date.today()
    inicio = (hoje - datetime.timedelta(days=dias)).isoformat()
    fim = hoje.isoformat()

    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": inicio, "End": fim},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    # Agrega o custo por servico ao longo de todos os dias do periodo.
    por_servico = {}
    moeda = "USD"
    total = 0.0
    for dia in resp.get("ResultsByTime", []):
        for grupo in dia.get("Groups", []):
            servico = grupo["Keys"][0]
            valor = grupo["Metrics"]["UnblendedCost"]
            moeda = valor.get("Unit", moeda)
            montante = float(valor["Amount"])
            por_servico[servico] = por_servico.get(servico, 0.0) + montante
            total += montante

    # Ordena por custo decrescente e arredonda.
    detalhamento = [
        {"service": s, "cost": round(v, 4)}
        for s, v in sorted(por_servico.items(), key=lambda kv: kv[1], reverse=True)
        if round(v, 4) > 0
    ]
    return {
        "period": {"start": inicio, "end": fim, "days": dias},
        "currency": moeda,
        "total_cost": round(total, 2),
        "by_service": detalhamento,
    }


# ---------------------------------------------------------------------------
# Ferramenta 8 - list_s3_buckets_summary (NOVA)
# ---------------------------------------------------------------------------
@com_retry()
def list_s3_buckets_summary(params):
    """Resumo dos buckets S3: nome, regiao, data de criacao e contagem total.

    S3 e global: list_buckets nao recebe regiao. A regiao de cada bucket vem de
    get_bucket_location (None == us-east-1, por motivo historico).
    """
    filtro_regiao = params.get("region")
    s3 = cliente("s3")

    buckets = []
    for b in s3.list_buckets().get("Buckets", []):
        try:
            loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint")
        except ClientError as erro:
            # Sem permissao ou erro pontual em 1 bucket: nao derruba a listagem.
            log_json(logging.WARNING, "s3_location_falhou",
                     bucket=b["Name"], erro=str(erro))
            loc = None
        regiao = loc or "us-east-1"
        if filtro_regiao and regiao != filtro_regiao:
            continue
        buckets.append({
            "name": b["Name"],
            "creation_date": serializar(b.get("CreationDate")),
            "region": regiao,
        })
    return {"count": len(buckets), "buckets": buckets}


# ---------------------------------------------------------------------------
# Ferramenta 9 - check_guardduty_findings (NOVA) - severidade >= MEDIUM
# ---------------------------------------------------------------------------
# Faixas de severidade do GuardDuty: LOW 1.0-3.9, MEDIUM 4.0-6.9, HIGH 7.0-8.9.
SEVERIDADE_MINIMA_MEDIUM = 4.0


def _classifica_severidade(valor):
    if valor >= 7.0:
        return "HIGH"
    if valor >= 4.0:
        return "MEDIUM"
    return "LOW"


@com_retry()
def check_guardduty_findings(params):
    """Lista achados do GuardDuty com severidade >= MEDIUM (>= 4.0).

    Percorre todos os detectores da regiao. Se o GuardDuty nao estiver habilitado,
    retorna lista vazia com `enabled=False` (sem erro - e um estado valido).
    """
    regiao = params.get("region") or REGIAO_PADRAO
    limite = float(params.get("min_severity") or SEVERIDADE_MINIMA_MEDIUM)
    gd = cliente("guardduty", regiao)

    detectores = gd.list_detectors().get("DetectorIds", [])
    if not detectores:
        return {"region": regiao, "enabled": False, "count": 0, "findings": []}

    achados = []
    for detector_id in detectores:
        # Filtro server-side: so achados nao arquivados com severidade >= limite.
        criterio = {
            "Criterion": {
                "severity": {"GreaterThanOrEqual": int(limite)},
                "service.archived": {"Eq": ["false"]},
            }
        }
        paginador = gd.get_paginator("list_findings")
        ids = []
        for pagina in paginador.paginate(DetectorId=detector_id,
                                         FindingCriteria=criterio):
            ids.extend(pagina.get("FindingIds", []))

        # get_findings aceita ate 50 IDs por chamada.
        for i in range(0, len(ids), 50):
            lote = gd.get_findings(DetectorId=detector_id,
                                   FindingIds=ids[i:i + 50])
            for f in lote.get("Findings", []):
                sev = float(f.get("Severity", 0))
                achados.append({
                    "id": f.get("Id"),
                    "type": f.get("Type"),
                    "severity": sev,
                    "severity_label": _classifica_severidade(sev),
                    "title": f.get("Title"),
                    "region": f.get("Region"),
                    "resource_type": f.get("Resource", {}).get("ResourceType"),
                    "updated_at": f.get("UpdatedAt"),
                })

    achados.sort(key=lambda a: a["severity"], reverse=True)
    return {"region": regiao, "enabled": True, "count": len(achados),
            "min_severity": limite, "findings": achados}


# ---------------------------------------------------------------------------
# Roteamento apiPath -> funcao
# ---------------------------------------------------------------------------
ROTAS = {
    "/list-ec2": list_ec2,
    "/ec2-details": get_ec2_details,
    "/list-rds": list_rds,
    "/check-alb-health": check_alb_health,
    "/cloudwatch-alarms": get_cloudwatch_alarms,
    "/list-ecs-services": list_ecs_services,
    "/cost-summary": get_cost_summary,
    "/list-s3-buckets": list_s3_buckets_summary,
    "/guardduty-findings": check_guardduty_findings,
}


def extrair_parametros(evento):
    """Junta parametros vindos de 'parameters' e do 'requestBody' em um dict."""
    params = {}
    for p in evento.get("parameters", []) or []:
        params[p["name"]] = p.get("value")

    corpo = evento.get("requestBody", {}).get("content", {})
    propriedades = corpo.get("application/json", {}).get("properties", []) or []
    for p in propriedades:
        params[p["name"]] = p.get("value")
    return params


def montar_resposta(evento, corpo, status=200):
    """Monta o envelope de resposta esperado pelo Bedrock Agent."""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": evento.get("actionGroup"),
            "apiPath": evento.get("apiPath"),
            "httpMethod": evento.get("httpMethod"),
            "httpStatusCode": status,
            "responseBody": {
                "application/json": {
                    "body": json.dumps(corpo, default=serializar, ensure_ascii=False)
                }
            },
        },
    }


def lambda_handler(evento, contexto):
    """Ponto de entrada: roteia o apiPath para a ferramenta correspondente."""
    api_path = evento.get("apiPath", "")
    funcao = ROTAS.get(api_path)
    log_json(logging.INFO, "invocacao", api_path=api_path,
             action_group=evento.get("actionGroup"))

    if funcao is None:
        log_json(logging.ERROR, "api_path_desconhecido", api_path=api_path)
        return montar_resposta(
            evento, {"error": f"apiPath desconhecido: {api_path}"}, status=404
        )

    params = extrair_parametros(evento)
    inicio = time.time()
    try:
        resultado = funcao(params)
        duracao_ms = round((time.time() - inicio) * 1000, 1)
        log_json(logging.INFO, "ferramenta_ok", api_path=api_path,
                 duracao_ms=duracao_ms)
        return montar_resposta(evento, resultado, status=200)
    except Exception as erro:  # noqa: BLE001 - devolve o erro ao agente
        log_json(logging.ERROR, "ferramenta_falhou", api_path=api_path,
                 tipo=type(erro).__name__, erro=str(erro))
        return montar_resposta(
            evento, {"error": f"{type(erro).__name__}: {erro}"}, status=500
        )

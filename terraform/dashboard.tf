# CloudWatch Dashboard - visao operacional do agente.
# Metricas: invocacoes das Lambdas, erros e duracao (proxy de latencia do Bedrock).

resource "aws_cloudwatch_dashboard" "infra_ops" {
  dashboard_name = "agente-operacoes-aws"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Invocacoes das Lambdas"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.slack_function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", var.tools_function_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Erros das Lambdas"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", var.slack_function_name],
            ["AWS/Lambda", "Errors", "FunctionName", var.tools_function_name],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Latencia da slack-handler (Bedrock) - p50/p99"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", var.slack_function_name, { stat = "p50" }],
            ["AWS/Lambda", "Duration", "FunctionName", var.slack_function_name, { stat = "p99" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Throttles e Concorrencia"
          region = var.aws_region
          view   = "timeSeries"
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/Lambda", "Throttles", "FunctionName", var.slack_function_name],
            ["AWS/Lambda", "ConcurrentExecutions", "FunctionName", var.slack_function_name, { stat = "Maximum" }],
          ]
        }
      }
    ]
  })
}

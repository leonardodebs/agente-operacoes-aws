# DynamoDB - historico de conversas (1 item por usuario+canal do Slack).

resource "aws_dynamodb_table" "history" {
  name         = "conversation-history"
  billing_mode = "PAY_PER_REQUEST" # sem capacidade provisionada: paga-se por uso
  hash_key     = "conversation_key"

  attribute {
    name = "conversation_key"
    type = "S"
  }

  # Expira conversas inativas automaticamente (campo `ttl` em epoch seconds).
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }
}

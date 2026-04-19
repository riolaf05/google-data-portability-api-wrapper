data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/handler.py"
  output_path = "${path.module}/lambda.zip"
}

locals {
  # Percorso relativo al modulo terraform/ (es. ../secret.json dalla cartella terraform)
  google_oauth_json = file(var.google_oauth_json_file)
}

resource "aws_iam_role" "lambda" {
  name_prefix = "${var.project_name}-lambda-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name_prefix = "${var.project_name}-policy-"
  role        = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}:*"
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "dataportability" {
  function_name = var.project_name
  description   = "Export liste salvate / preferiti Maps via Google Data Portability API"
  role          = aws_iam_role.lambda.arn
  handler       = "handler.handler"
  runtime       = "python3.12"
  timeout       = var.lambda_timeout
  memory_size   = var.lambda_memory_mb

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  environment {
    variables = {
      GOOGLE_OAUTH_JSON = local.google_oauth_json
      POLL_INTERVAL_SEC = var.poll_interval_sec
      MAX_POLL_SECONDS  = var.max_poll_seconds
    }
  }

  depends_on = [
    aws_iam_role_policy.lambda,
    aws_cloudwatch_log_group.lambda,
  ]
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.project_name}"
  retention_in_days = 14
}

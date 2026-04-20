resource "null_resource" "notion_bundle" {
  triggers = {
    handler_md5 = filemd5("${path.module}/../lambda_notion/lambda_function.py")
    build_py    = filemd5("${path.module}/../lambda_notion/build.py")
  }

  provisioner "local-exec" {
    working_dir = abspath("${path.module}/..")
    command     = "python lambda_notion/build.py"
  }
}

data "archive_file" "notion_zip" {
  depends_on = [null_resource.notion_bundle]

  type        = "zip"
  source_dir  = "${path.module}/../lambda_notion/build"
  output_path = "${path.module}/notion_lambda.zip"
}

resource "aws_iam_role" "notion_lambda" {
  name_prefix = "${var.project_name}-notion-"

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

resource "aws_iam_role_policy" "notion_lambda" {
  name_prefix = "${var.project_name}-notion-policy-"
  role        = aws_iam_role.notion_lambda.id

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
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}-notion:*"
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "notion" {
  function_name = "${var.project_name}-notion"
  description   = "Scrive places (output organize) su pagina Notion"
  role          = aws_iam_role.notion_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.notion_lambda_timeout
  memory_size   = var.notion_lambda_memory_mb

  filename         = data.archive_file.notion_zip.output_path
  source_code_hash = data.archive_file.notion_zip.output_base64sha256

  environment {
    variables = {
      NOTION_INTEGRATION_TOKEN = var.notion_integration_token
      NOTION_PAGE_ID           = var.notion_page_id
    }
  }

  depends_on = [
    aws_iam_role_policy.notion_lambda,
    aws_cloudwatch_log_group.notion,
  ]
}

resource "aws_cloudwatch_log_group" "notion" {
  name              = "/aws/lambda/${var.project_name}-notion"
  retention_in_days = 14
}

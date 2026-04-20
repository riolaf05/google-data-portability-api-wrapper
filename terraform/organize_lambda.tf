resource "null_resource" "organize_bundle" {
  triggers = {
    handler_md5 = filemd5("${path.module}/../lambda_organize/lambda_function.py")
    req_md5     = filemd5("${path.module}/../lambda_organize/requirements.txt")
    build_py    = filemd5("${path.module}/../lambda_organize/build.py")
  }

  provisioner "local-exec" {
    # working_dir = root repo: evita percorsi relativi rotti su Windows con path.module/..
    working_dir = abspath("${path.module}/..")
    command     = "python lambda_organize/build.py"
  }
}

data "archive_file" "organize_zip" {
  depends_on = [null_resource.organize_bundle]

  type        = "zip"
  source_dir  = "${path.module}/../lambda_organize/build"
  output_path = "${path.module}/organize_lambda.zip"
}

resource "aws_iam_role" "organize_lambda" {
  name_prefix = "${var.project_name}-org-"

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

resource "aws_iam_role_policy" "organize_lambda" {
  name_prefix = "${var.project_name}-org-policy-"
  role        = aws_iam_role.organize_lambda.id

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
          "arn:aws:logs:${var.aws_region}:*:log-group:/aws/lambda/${var.project_name}-organize:*"
        ]
      }
    ]
  })
}

resource "aws_lambda_function" "organize" {
  function_name = "${var.project_name}-organize"
  description   = "Organizza takeout Data Portability + distanze (Nominatim)"
  role          = aws_iam_role.organize_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  timeout       = var.organize_lambda_timeout
  memory_size   = var.organize_lambda_memory_mb

  filename         = data.archive_file.organize_zip.output_path
  source_code_hash = data.archive_file.organize_zip.output_base64sha256

  environment {
    variables = {
      ORIGIN_ADDRESS           = var.organize_origin_address
      ORIGIN_LAT               = var.organize_origin_lat
      ORIGIN_LON               = var.organize_origin_lon
      CITY_FILTER              = var.organize_city_filter
      NOMINATIM_USER_AGENT     = var.organize_nominatim_user_agent
      PLACES_AREA_MODE         = var.organize_places_area_mode
      GOOGLE_GEOCODING_API_KEY = var.organize_google_geocoding_api_key
    }
  }

  depends_on = [
    aws_iam_role_policy.organize_lambda,
    aws_cloudwatch_log_group.organize,
  ]
}

resource "aws_cloudwatch_log_group" "organize" {
  name              = "/aws/lambda/${var.project_name}-organize"
  retention_in_days = 14
}

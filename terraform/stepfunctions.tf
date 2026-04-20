resource "aws_iam_role" "sfn" {
  name_prefix = "${var.project_name}-sfn-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  name_prefix = "${var.project_name}-sfn-lambda-"
  role        = aws_iam_role.sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = [
          aws_lambda_function.dataportability.arn,
          aws_lambda_function.organize.arn,
          aws_lambda_function.notion.arn,
        ]
      }
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project_name}-pipeline"
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "Export Data Portability → organizza posti → Notion"
    StartAt = "ExportTakeout"
    States = {
      ExportTakeout = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.dataportability.arn
          "Payload.$"  = "$.export_request"
        }
        ResultPath = "$.dataportability_invoke"
        Next       = "OrganizePlaces"
      }
      OrganizePlaces = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.organize.arn
          Payload = {
            "takeout.$" = "$.dataportability_invoke.Payload"
          }
        }
        ResultPath = "$.organize_invoke"
        Next       = "FormatOutput"
      }
      FormatOutput = {
        Type      = "Pass"
        InputPath = "$.organize_invoke.Payload"
        Next      = "WriteNotion"
      }
      WriteNotion = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.notion.arn
          "Payload.$"  = "$"
        }
        OutputPath = "$.Payload"
        End        = true
      }
    }
  })
}

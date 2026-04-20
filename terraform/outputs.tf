output "lambda_function_name" {
  value       = aws_lambda_function.dataportability.function_name
  description = "Nome della funzione Lambda da invocare."
}

output "lambda_arn" {
  value       = aws_lambda_function.dataportability.arn
  description = "ARN della Lambda export."
}

output "organize_lambda_function_name" {
  value       = aws_lambda_function.organize.function_name
  description = "Nome Lambda organize."
}

output "state_machine_arn" {
  value       = aws_sfn_state_machine.pipeline.arn
  description = "Step Functions: export → organize."
}

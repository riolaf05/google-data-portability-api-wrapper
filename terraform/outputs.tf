output "lambda_function_name" {
  value       = aws_lambda_function.dataportability.function_name
  description = "Nome della funzione Lambda da invocare."
}

output "lambda_arn" {
  value       = aws_lambda_function.dataportability.arn
  description = "ARN della Lambda."
}

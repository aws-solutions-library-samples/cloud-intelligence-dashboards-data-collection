output "lambda_role_arn" {
  description = "ARN of the created Lambda execution role"
  value       = aws_iam_role.lambda_role.arn
}
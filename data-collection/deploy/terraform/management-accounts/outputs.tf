output "mgmt_account_stack_id" {
  description = "ID of the CloudFormation stack in management account"
  value       = aws_cloudformation_stack.mgmt_read.id
}
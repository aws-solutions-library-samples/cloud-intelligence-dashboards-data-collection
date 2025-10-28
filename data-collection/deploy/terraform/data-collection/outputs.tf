output "stack_id" {
  description = "The unique identifier for the stack"
  value       = aws_cloudformation_stack.data_collection.id
}

output "stack_outputs" {
  description = "Map of outputs from the CloudFormation stack"
  value       = aws_cloudformation_stack.data_collection.outputs
}

output "identity_arn" {
  value = aws_sesv2_email_identity.comments.arn
}

output "configuration_set_arn" {
  value = aws_sesv2_configuration_set.comments.arn
}

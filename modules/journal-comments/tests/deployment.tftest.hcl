mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_resource "aws_iam_role" { defaults = { arn = "arn:aws:iam::123456789012:role/example" } }
  mock_resource "aws_sns_topic" { defaults = { arn = "arn:aws:sns:eu-central-1:123456789012:example" } }
  mock_resource "aws_sqs_queue" { defaults = { arn = "arn:aws:sqs:eu-central-1:123456789012:example" } }
  mock_resource "aws_iam_policy" { defaults = { arn = "arn:aws:iam::123456789012:policy/example" } }
}
mock_provider "aws" {
  alias = "use1"
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn                       = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-4000-8000-000000000000"
      domain_validation_options = [{ domain_name = "comments.example.com", resource_record_name = "_comments.example.com", resource_record_type = "CNAME", resource_record_value = "_comments.acm-validations.aws" }]
    }
  }
}
variables {
  region                    = "eu-central-1"
  zone_id                   = "ZEXAMPLE"
  name                      = "example-journal-comments"
  operations_prefix         = "example-comments"
  site_id                   = "example"
  domain                    = "comments.example.com"
  origin_domain             = "comments-origin.example.com"
  parameter_prefix          = "/example/comments/production"
  owner_email               = "owner@example.com"
  email_from                = "comments@example.com"
  ssh_public_key            = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCexample tests"
  admin_cidrs               = ["192.0.2.0/24"]
  origin_secret             = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  ses_identity_arn          = "arn:aws:ses:eu-central-1:123456789012:identity/example.com"
  ses_configuration_set_arn = "arn:aws:ses:eu-central-1:123456789012:configuration-set/example"
}
run "isolated_deployment" {
  command = apply
  assert {
    condition     = aws_lightsail_instance.comments.name == "example-journal-comments-host" && aws_cloudwatch_metric_alarm.health.dimensions.Site == "example"
    error_message = "Resource identity must come from this deployment."
  }
  assert {
    condition     = aws_cloudwatch_log_group.alert_mail.retention_in_days == 14 && aws_sqs_queue.alert_failures.message_retention_seconds == 86400
    error_message = "Operational retention must remain bounded."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.backup.block_public_policy && aws_cloudwatch_metric_alarm.health.evaluation_periods == 3
    error_message = "Backups must remain private and heartbeat alarms must retain their threshold."
  }
}

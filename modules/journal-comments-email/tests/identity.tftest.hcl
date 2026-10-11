mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_resource "aws_sesv2_email_identity" {
    defaults = { arn = "arn:aws:ses:eu-central-1:123456789012:identity/example.com", dkim_signing_attributes = { tokens = ["token1", "token2", "token3"] } }
  }
  mock_resource "aws_sns_topic" { defaults = { arn = "arn:aws:sns:eu-central-1:123456789012:example" } }
}
variables {
  region                 = "eu-central-1"
  zone_id                = "ZEXAMPLE"
  domain                 = "example.com"
  owner_email            = "owner@example.com"
  configuration_set_name = "example-comment-mail"
  feedback_topic_name    = "example-comment-feedback"
}
run "domain_feedback" {
  command = apply
  assert {
    condition     = aws_sesv2_email_identity.comments.email_identity == "example.com" && length(aws_route53_record.dkim) == 3
    error_message = "Verify each deployment domain with all three DKIM records."
  }
  assert {
    condition     = length(aws_ses_identity_notification_topic.feedback) == 2 && aws_sns_topic_subscription.feedback.endpoint == "owner@example.com"
    error_message = "Both bounce and complaint events must reach the deployment owner."
  }
}

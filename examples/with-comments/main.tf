terraform {
  required_version = ">= 1.15.0"
  required_providers { aws = { source = "hashicorp/aws", version = ">= 6.54, < 7.0" } }
}
provider "aws" { region = var.region }
provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}
variable "region" { default = "eu-central-1" }
variable "hosted_zone_id" { type = string }
variable "domain" { default = "example.com" }
variable "owner_email" { type = string }
variable "ssh_public_key" { type = string }
variable "admin_cidrs" { type = list(string) }
variable "comments_origin_secret" {
  type      = string
  sensitive = true
}
module "website" {
  source          = "../../modules/static-site"
  providers       = { aws = aws, aws.use1 = aws.use1 }
  site_key        = "example"
  domain_name     = var.domain
  aliases         = ["www.${var.domain}"]
  hosted_zone_id  = var.hosted_zone_id
  enable_pipeline = false
}
module "email" {
  source                 = "../../modules/journal-comments-email"
  region                 = var.region
  zone_id                = var.hosted_zone_id
  domain                 = var.domain
  owner_email            = var.owner_email
  configuration_set_name = "example-comment-mail"
  feedback_topic_name    = "example-comment-feedback"
}
# Regional singleton: manage once in this environment, outside per-site modules.
resource "aws_sesv2_account_suppression_attributes" "feedback" { suppressed_reasons = ["BOUNCE", "COMPLAINT"] }
module "comments" {
  source                    = "../../modules/journal-comments"
  providers                 = { aws = aws, aws.use1 = aws.use1 }
  region                    = var.region
  zone_id                   = var.hosted_zone_id
  name                      = "example-journal-comments"
  operations_prefix         = "example-comments"
  site_id                   = "example"
  domain                    = "comments.${var.domain}"
  origin_domain             = "comments-origin.${var.domain}"
  owner_email               = var.owner_email
  email_from                = "comments@${var.domain}"
  parameter_prefix          = "/example/comments/production"
  ssh_public_key            = var.ssh_public_key
  admin_cidrs               = var.admin_cidrs
  origin_secret             = var.comments_origin_secret
  ses_identity_arn          = module.email.identity_arn
  ses_configuration_set_arn = module.email.configuration_set_arn
}
output "deployment" { value = module.comments.deployment }

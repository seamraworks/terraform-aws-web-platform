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
module "website" {
  source          = "../../modules/static-site"
  providers       = { aws = aws, aws.use1 = aws.use1 }
  site_key        = "example"
  domain_name     = var.domain
  aliases         = ["www.${var.domain}"]
  hosted_zone_id  = var.hosted_zone_id
  enable_pipeline = false
}
output "website" {
  value = { bucket = module.website.site_bucket_name, distribution = module.website.cloudfront_distribution_id }
}

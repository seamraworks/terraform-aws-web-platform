terraform {
  required_providers {
    archive = { source = "hashicorp/archive", version = ">= 2.8, < 3.0" }
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.54, < 7.0"
      configuration_aliases = [
        aws.use1,
      ]
    }
  }
}

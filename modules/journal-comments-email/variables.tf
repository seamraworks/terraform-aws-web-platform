variable "region" {
  description = "AWS region where the SES identity and feedback topic are managed."
  type        = string
}
variable "zone_id" {
  description = "Existing Route 53 hosted zone ID for DKIM and MAIL FROM records."
  type        = string
}
variable "owner_email" {
  description = "Real owner inbox for bounce and complaint notifications and sandbox verification."
  type        = string
}

variable "domain" {
  description = "Domain identity authorized to send comment email."
  type        = string
}

variable "configuration_set_name" {
  description = "Stable SES configuration set name; preserve it during adoption."
  type        = string
}

variable "feedback_topic_name" {
  description = "Stable SNS topic name for SES bounce and complaint feedback."
  type        = string
}

variable "mail_from_subdomain" {
  description = "Subdomain beneath the verified domain used for the envelope MAIL FROM."
  type        = string
  default     = "comment-mail"
}

variable "feedback_policy_sid" {
  description = "Stable SES publication policy statement ID; preserve it during adoption."
  type        = string
  default     = "AllowSESIdentity"
}

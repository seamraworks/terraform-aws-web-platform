variable "region" {
  description = "AWS region for the dedicated comments host and its regional resources."
  type        = string
}
variable "zone_id" {
  description = "Existing Route 53 hosted zone ID for comment DNS records."
  type        = string
}
variable "ses_identity_arn" {
  description = "Verified identity managed by the independent Journal email module."
  type        = string
}
variable "ses_configuration_set_arn" {
  description = "Default configuration set used when sending from the verified identity."
  type        = string
}
variable "ssh_public_key" {
  description = "RSA administration public key; private keys stay with the operator."
  type        = string
  validation {
    condition     = startswith(var.ssh_public_key, "ssh-rsa ")
    error_message = "Lightsail's key import requires an RSA public key (ssh-rsa)."
  }
}
variable "admin_cidrs" {
  description = "Specific IPv4 administration networks permitted to reach SSH."
  type        = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for cidr in var.admin_cidrs : can(cidrnetmask(cidr)) && !endswith(cidr, "/0")])
    error_message = "Configure administration IPv4 CIDRs without opening SSH to the entire Internet."
  }
}
variable "origin_secret" {
  description = "Persistent random private-origin header secret; supply the identical value to runtime configuration."
  type        = string
  sensitive   = true
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{43,128}$", var.origin_secret))
    error_message = "Use a random URL-safe origin secret of at least 43 characters."
  }
}

variable "name" {
  description = "Stable deployment prefix used for the dedicated host and supporting resources."
  type        = string
}

variable "domain" {
  description = "Public comments domain served through CloudFront."
  type        = string
}

variable "origin_domain" {
  description = "Private host origin domain, distinct from the public comments domain."
  type        = string
}

variable "site_id" {
  description = "Stable Remark42 site identifier, also used in metrics and the runtime descriptor."
  type        = string
}

variable "owner_email" {
  description = "Real owner inbox for operational messages and fallback confirmations."
  type        = string
}

variable "email_from" {
  description = "Sender address on the independently verified SES domain."
  type        = string
}

variable "parameter_prefix" {
  description = "SSM prefix containing this deployment runtime configuration."
  type        = string
}

variable "operations_prefix" {
  description = "Stable alert and systemd service prefix; preserve it during adoption."
  type        = string
}

variable "tags" {
  description = "Caller-supplied AWS resource tags."
  type        = map(string)
  default     = {}
}

variable "description" {
  description = "Deployment description used in AWS resources."
  type        = string
  default     = "Website comments"
}

variable "metric_namespace" {
  description = "CloudWatch namespace for this comments deployment."
  type        = string
  default     = "WebPlatform/Comments"
}

variable "origin_header" {
  description = "Header name used by CloudFront and Caddy to authenticate origin requests."
  type        = string
  default     = "X-Comments-Origin"
}

variable "runtime_dir" {
  description = "Absolute runtime directory on the dedicated host; retain its existing data paths during upgrades."
  type        = string
  default     = "/opt/web-comments"
}

variable "config_dir" {
  description = "Restricted host directory containing descriptor, configuration and dedicated credentials."
  type        = string
  default     = "/etc/web-comments"
}

variable "brand_name" {
  description = "Website name used in owner alerts and runtime branding."
  type        = string
  default     = "Website"
}

variable "timezone" {
  description = "IANA timezone used for owner-facing alerts and the daily digest."
  type        = string
  default     = "UTC"
}

variable "nft_table" {
  description = "Stable host firewall table name; retain it during adoption."
  type        = string
  default     = "web_comments"
}

variable "aws_region" {
  type        = string
  description = "AWS region for the Reclamos stack."
  default     = "us-east-1"
}

variable "project_name" {
  type        = string
  description = "Prefix used for AWS resource names."
  default     = "reclamos"
}

variable "db_username" {
  type        = string
  description = "RDS master username."
  default     = "reclamos"
}

variable "db_name" {
  type        = string
  description = "RDS database name."
  default     = "reclamos"
}

variable "api_domain_name" {
  type        = string
  description = "Public DNS name for the Reclamos API, covered by its ACM certificate."
}

variable "web_origins" {
  type        = list(string)
  description = "Origins of the web app, such as https://reclamos.example, allowed to call the API from a browser."
}

variable "worker_count" {
  type        = number
  default     = 0
  description = "Worker tasks to run. Set 1 while a crawl runs; the worker idles otherwise."
}

variable "cloudflare_zone_name" {
  type        = string
  description = "Cloudflare zone containing api_domain_name."
}

variable "github_repository" {
  type        = string
  description = "GitHub repository, as owner/name, whose master branch may assume the deploy role."
  default     = "risinghq/reclamos.rising.sh"
}

variable "api_image_tag" {
  type        = string
  description = "Immutable ECR tag the task definitions start from. The pipeline registers later revisions."
  default     = "bootstrap"

  validation {
    condition     = var.api_image_tag != "latest"
    error_message = "api_image_tag must be an immutable tag other than latest."
  }
}

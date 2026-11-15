terraform {
  required_version = ">= 1.14.0"

  # S3 bucket names are global, so each account passes its own bucket to
  # terraform init; docs/operations.md gives the command.
  backend "s3" {
    key          = "reclamos/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Reads CLOUDFLARE_API_TOKEN, a token with DNS edit on the zone.
provider "cloudflare" {}

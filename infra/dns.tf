data "cloudflare_zone" "api" {
  filter = {
    name = var.cloudflare_zone_name
  }
}

resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "cloudflare_dns_record" "api_certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.api.domain_validation_options : option.domain_name => {
      name    = trimsuffix(option.resource_record_name, ".")
      content = trimsuffix(option.resource_record_value, ".")
      type    = option.resource_record_type
    }
  }

  zone_id = data.cloudflare_zone.api.zone_id
  name    = each.value.name
  content = each.value.content
  type    = each.value.type
  ttl     = 60
  proxied = false
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for record in cloudflare_dns_record.api_certificate_validation : record.name]
}

# A proxied record would put Cloudflare's addresses in X-Forwarded-For, and the
# rate limit would count all visitors as a few clients.
resource "cloudflare_dns_record" "api" {
  zone_id = data.cloudflare_zone.api.zone_id
  name    = var.api_domain_name
  type    = "CNAME"
  content = aws_lb.api.dns_name
  ttl     = 300
  proxied = false
}

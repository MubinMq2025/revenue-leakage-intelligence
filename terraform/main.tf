data "aws_caller_identity" "current" {}

locals {
  name   = "${var.project}-${var.env}"
  bucket = "${local.name}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "data" {
  bucket = local.bucket
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Empty marker objects so the zones are visible in the console
resource "aws_s3_object" "zones" {
  for_each = toset(["raw/", "curated/", "quarantine/", "athena-results/"])
  bucket   = aws_s3_bucket.data.id
  key      = each.value
}

resource "aws_glue_catalog_database" "olist" {
  name = replace("${local.name}_olist", "-", "_")
}

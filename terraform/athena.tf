# ---------------------------------------------------------------------------
# Athena workgroup: where queries run, where results go, and a cost guardrail.
# Athena charges US$5 per TB scanned (minimum 10 MB per query), so our
# queries cost a tiny fraction of a cent.
# ---------------------------------------------------------------------------

resource "aws_athena_workgroup" "rli" {
  name          = local.name
  description   = "Analytics and data quality queries for the revenue leakage project"
  force_destroy = var.env == "dev"

  configuration {
    enforce_workgroup_configuration    = true      # users cannot override these settings
    publish_cloudwatch_metrics_enabled = true      # query metrics appear in CloudWatch
    bytes_scanned_cutoff_per_query     = 104857600 # cancel any query scanning more than 100 MB

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

output "athena_workgroup" {
  value = aws_athena_workgroup.rli.name
}
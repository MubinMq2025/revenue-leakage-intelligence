# ---------------------------------------------------------------------------
# Glue ETL job: validated/<table>/ (CSV) -> curated/<table>/ (Parquet), all 9 tables
# Cost: 2 workers x ~3 min per run ~= US$0.05 per run (billed per second, 1 min minimum)
# ---------------------------------------------------------------------------

locals {
  glue_job_name = "${local.name}-curate-olist"
}

# --- The PySpark script and the contracts, uploaded to S3 (Glue runs scripts from S3) ---

resource "aws_s3_object" "curate_script" {
  bucket = aws_s3_bucket.data.id
  key    = "glue-scripts/curate_olist.py"
  source = "${path.module}/../glue/curate_olist.py"
  etag   = filemd5("${path.module}/../glue/curate_olist.py") # re-upload only when the script changes
}

# The same YAML contracts the Lambda uses, converted to one JSON file for the Glue job
resource "aws_s3_object" "contracts_json" {
  bucket       = aws_s3_bucket.data.id
  key          = "glue-config/contracts.json"
  content      = jsonencode(local.contracts)
  content_type = "application/json"
}

# --- Identity for the Glue job -----------------------------------------------

data "aws_iam_policy_document" "glue_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "glue_curate" {
  name               = local.glue_job_name
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
}

# AWS-managed baseline for Glue (its own logs and internals). It does NOT grant access to our bucket.
resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_curate.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

# Least-privilege access to our bucket: read validated + script + contracts, write curated only
data "aws_iam_policy_document" "glue_curate_s3" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid     = "ReadInputsScriptAndContracts"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/validated/*",
      "${aws_s3_bucket.data.arn}/glue-scripts/*",
      "${aws_s3_bucket.data.arn}/glue-config/*",
      "${aws_s3_bucket.data.arn}/curated/*",
    ]
  }

  statement {
    sid     = "WriteCurated"
    actions = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = [
      "${aws_s3_bucket.data.arn}/curated/*",
      # When Glue's S3 layer empties a folder during overwrite, it writes a
      # "folder placeholder" object named <folder>_$folder$ next to it.
      "${aws_s3_bucket.data.arn}/curated_$folder$",
    ]
  }
}

resource "aws_iam_role_policy" "glue_curate_s3" {
  name   = "${local.glue_job_name}-s3"
  role   = aws_iam_role.glue_curate.id
  policy = data.aws_iam_policy_document.glue_curate_s3.json
}

# --- The job ------------------------------------------------------------------

resource "aws_glue_job" "curate" {
  name              = local.glue_job_name
  description       = "Cast, rename and de-duplicate the latest validated snapshot of each Olist table into Parquet"
  role_arn          = aws_iam_role.glue_curate.arn
  glue_version      = "5.0"
  worker_type       = "G.1X" # smallest standard Spark worker
  number_of_workers = 2      # minimum allowed
  timeout           = 15     # minutes; stops a stuck job from running up costs
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data.bucket}/${aws_s3_object.curate_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--DATA_BUCKET"  = aws_s3_bucket.data.bucket
    "--job-language" = "python"
  }

  execution_property {
    max_concurrent_runs = 1 # two runs at once could overwrite each other's output
  }
}

output "glue_job_name" {
  value = aws_glue_job.curate.name
}

# ---------------------------------------------------------------------------
# Glue job: run the whole Phase 4 ML pipeline in AWS (Phase 4.7), no laptop needed.
# reads the marts (Parquet in athena-results/tables/) -> trains, backtests, explains
# -> writes the 5 ml_* tables (ml/). Phase 5 will start it on a schedule.
# Cost: 2 workers x ~10 min ~= US$0.15 per run (billed per second, 1 min minimum).
# ---------------------------------------------------------------------------

locals {
  ml_job_name   = "${local.name}-ml-pipeline"
  ml_bundle_zip = "${path.module}/../build/ml_bundle.zip" # built by scripts/build_ml_bundle.py
  # Same libraries and versions as requirements.txt, installed by Glue with pip before the run.
  # MLflow is left out on purpose: tracking is switched off in the cloud (RLI_TRACKING=off).
  ml_python_modules = "pandas==2.3.*,pyarrow==21.*,pyyaml==6.*,scikit-learn==1.*,lightgbm==4.*,matplotlib==3.*"
}

# --- The launcher script and the code bundle, uploaded to S3 -------------------

resource "aws_s3_object" "ml_launcher" {
  bucket = aws_s3_bucket.data.id
  key    = "glue-scripts/run_ml.py"
  source = "${path.module}/../glue/run_ml.py"
  etag   = filemd5("${path.module}/../glue/run_ml.py")
}

resource "aws_s3_object" "ml_bundle" {
  bucket = aws_s3_bucket.data.id
  key    = "glue-scripts/ml_bundle.zip"
  source = local.ml_bundle_zip
  etag   = filemd5(local.ml_bundle_zip) # re-upload only when the code changes
}

# --- Identity: its own role, so it can only touch what the ML pipeline needs -----

resource "aws_iam_role" "glue_ml" {
  name               = local.ml_job_name
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role.json
}

resource "aws_iam_role_policy_attachment" "glue_ml_service" {
  role       = aws_iam_role.glue_ml.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

data "aws_iam_policy_document" "glue_ml" {
  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid     = "ReadCodeAndMarts"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/glue-scripts/*",
      "${aws_s3_bucket.data.arn}/athena-results/tables/*", # where the mart tables keep their Parquet files
      "${aws_s3_bucket.data.arn}/ml/*",
    ]
  }

  statement {
    sid       = "WriteMlTables"
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/ml/*"]
  }

  statement {
    sid     = "ReadTableLocations"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables"]
    resources = [
      "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.olist.name}",
      "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.olist.name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "glue_ml" {
  name   = "${local.ml_job_name}-access"
  role   = aws_iam_role.glue_ml.id
  policy = data.aws_iam_policy_document.glue_ml.json
}

# --- The job ---------------------------------------------------------------------

resource "aws_glue_job" "ml" {
  name              = local.ml_job_name
  description       = "Phase 4 ML pipeline: seller queue, revenue forecast, drift check, checkout risk + reasons, publish ml_* tables"
  role_arn          = aws_iam_role.glue_ml.arn
  glue_version      = "5.0"
  worker_type       = "G.1X"
  number_of_workers = 2  # minimum allowed; the pipeline is plain Python on the driver
  timeout           = 30 # minutes; stops a stuck run from running up costs
  max_retries       = 0

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.data.bucket}/${aws_s3_object.ml_launcher.key}"
    python_version  = "3"
  }

  default_arguments = {
    "--DATA_BUCKET"                      = aws_s3_bucket.data.bucket
    "--BUNDLE_KEY"                       = aws_s3_object.ml_bundle.key # the launcher downloads the latest bundle each run
    "--additional-python-modules"        = local.ml_python_modules
    "--job-language"                     = "python"
    "--enable-continuous-cloudwatch-log" = "true"
  }

  execution_property {
    max_concurrent_runs = 1 # two runs at once would overwrite each other's tables
  }
}

output "ml_job_name" {
  value = aws_glue_job.ml.name
}
# ---------------------------------------------------------------------------
# "models" Lambda (Phase 5): the warehouse steps of the daily pipeline.
# One function, three actions: build (rebuild sql/models), check (model_checks.yaml),
# leakage (latest month vs config/alerts.yaml + drift status). Step Functions calls it.
# Build the package first, from the repo root:  python scripts/build_models_lambda.py
# Cost: a few cents a month (Lambda mostly waits for Athena; Athena scans a few MB per query).
# ---------------------------------------------------------------------------

locals {
  models_fn_name = "${local.name}-models"
  models_zip     = "${path.module}/../build/models_lambda.zip"
  glue_arn       = "arn:aws:glue:${var.region}:${data.aws_caller_identity.current.account_id}"
}

resource "aws_iam_role" "models_fn" {
  name               = local.models_fn_name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json # same trust as the validator
}

# --- Least privilege: run Athena queries in our workgroup, change only our catalog ---

data "aws_iam_policy_document" "models_fn" {
  statement {
    sid       = "RunAthenaInOurWorkgroup"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
    resources = [aws_athena_workgroup.rli.arn]
  }

  statement {
    sid = "ReadAndRebuildOurCatalog" # views and CTAS tables are catalog entries
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions",
      "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
    ]
    resources = [
      "${local.glue_arn}:catalog",
      "${local.glue_arn}:database/${aws_glue_catalog_database.olist.name}",
      "${local.glue_arn}:table/${aws_glue_catalog_database.olist.name}/*",
    ]
  }

  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid     = "ReadSourceData" # the queries read curated tables, old marts and ML outputs
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.data.arn}/curated/*",
      "${aws_s3_bucket.data.arn}/athena-results/*",
      "${aws_s3_bucket.data.arn}/ml/*",
    ]
  }

  statement {
    sid       = "WriteQueryResultsAndMarts" # Athena writes results and CTAS files here as us
    actions   = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/athena-results/*"]
  }

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.models_fn.arn}:*"]
  }
}

resource "aws_iam_role_policy" "models_fn" {
  name   = "${local.models_fn_name}-permissions"
  role   = aws_iam_role.models_fn.id
  policy = data.aws_iam_policy_document.models_fn.json
}

resource "aws_cloudwatch_log_group" "models_fn" {
  name              = "/aws/lambda/${local.models_fn_name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "models_fn" {
  function_name    = local.models_fn_name
  role             = aws_iam_role.models_fn.arn
  runtime          = "python3.12"
  handler          = "models_handler.lambda_handler"
  filename         = local.models_zip
  source_code_hash = filebase64sha256(local.models_zip) # redeploy only when code changes
  memory_size      = 256                                # it mostly waits for Athena
  timeout          = 600                                # 14 models one after another; usually ~2 min

  environment {
    variables = {
      RLI_WORKGROUP = aws_athena_workgroup.rli.name
      RLI_DATABASE  = aws_glue_catalog_database.olist.name
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.models_fn,
    aws_iam_role_policy.models_fn,
  ]
}

output "models_function_name" {
  value = aws_lambda_function.models_fn.function_name
}

# ---------------------------------------------------------------------------
# Daily pipeline (Phase 5): Step Functions runs every stage in order, SNS emails people.
#
#   CurateData (Glue) -> BuildModels -> CheckModels (Lambda)
#   -> RunML (Glue) -> CheckLeakage (Lambda) -> alert? -> email -> Done
#   Any stage fails -> failure email -> Failed
#
# Test the alert path: start an execution with {"max_at_risk_rate": 0.001}. Normal runs send {}.
# ".sync" means Step Functions waits for the Glue job to finish before moving on.
# Cost: Step Functions about US$0.0003 per run (12 state changes); the Glue jobs are the real cost.
# ---------------------------------------------------------------------------

variable "alert_email" {
  description = "Who gets the alert emails (set it in terraform/terraform.tfvars, which Git ignores)"
  type        = string
}

locals {
  pipeline_name = "${local.name}-daily-pipeline"

  # Lambda hiccups (throttling, a cold container) are retried; our own StepFailed errors are not
  lambda_retry = [{
    ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"]
    IntervalSeconds = 5
    MaxAttempts     = 3
    BackoffRate     = 2
  }]
  glue_retry = [{
    ErrorEquals     = ["Glue.ConcurrentRunsExceededException"] # someone is already running the job
    IntervalSeconds = 60
    MaxAttempts     = 4
    BackoffRate     = 2
  }]
  catch_all = [{
    ErrorEquals = ["States.ALL"]
    ResultPath  = "$.error" # keep what happened, so the email can say it
    Next        = "NotifyFailure"
  }]
}

# --- SNS: the "WhatsApp group" for alerts -----------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email # AWS sends a confirmation email first; nothing arrives until you click it
}

# --- Identity: the state machine may start our 2 Glue jobs, call our Lambda, and post to our topic ---

data "aws_iam_policy_document" "states_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = local.pipeline_name
  assume_role_policy = data.aws_iam_policy_document.states_assume_role.json
}

data "aws_iam_policy_document" "pipeline" {
  statement {
    sid     = "RunOurGlueJobs"
    actions = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = [
      "${local.glue_arn}:job/${aws_glue_job.curate.name}",
      "${local.glue_arn}:job/${aws_glue_job.ml.name}",
    ]
  }

  statement {
    sid       = "CallModelsLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.models_fn.arn, "${aws_lambda_function.models_fn.arn}:*"]
  }

  statement {
    sid       = "SendAlerts"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "${local.pipeline_name}-permissions"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}

# --- The state machine ------------------------------------------------------------

resource "aws_sfn_state_machine" "daily" {
  name     = local.pipeline_name
  role_arn = aws_iam_role.pipeline.arn

  definition = jsonencode({
    Comment = "Daily revenue leakage pipeline: curate, build, check, ML, leakage alert"
    StartAt = "CurateData"
    States = {

      CurateData = {
        Type       = "Task"
        Resource   = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = { JobName = aws_glue_job.curate.name }
        ResultPath = null # keep our state small; the Glue run details are in the Glue console
        Retry      = local.glue_retry
        Catch      = local.catch_all
        Next       = "BuildModels"
      }

      BuildModels = {
        Type           = "Task"
        Resource       = "arn:aws:states:::lambda:invoke"
        Parameters     = { FunctionName = aws_lambda_function.models_fn.arn, Payload = { action = "build" } }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.build"
        Retry          = local.lambda_retry
        Catch          = local.catch_all
        Next           = "CheckModels"
      }

      CheckModels = {
        Type           = "Task"
        Resource       = "arn:aws:states:::lambda:invoke"
        Parameters     = { FunctionName = aws_lambda_function.models_fn.arn, Payload = { action = "check" } }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.check"
        Retry          = local.lambda_retry
        Catch          = local.catch_all
        Next           = "RunML"
      }

      RunML = {
        Type       = "Task"
        Resource   = "arn:aws:states:::glue:startJobRun.sync"
        Parameters = { JobName = aws_glue_job.ml.name }
        ResultPath = null
        Retry      = local.glue_retry
        Catch      = local.catch_all
        Next       = "CheckLeakage"
      }

      CheckLeakage = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.models_fn.arn
          Payload = {
            action    = "leakage"
            "input.$" = "$$.Execution.Input" # the whole start input, so the Lambda can read a test line from it
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.leakage"
        Retry          = local.lambda_retry
        Catch          = local.catch_all
        Next           = "AlertNeeded"
      }

      AlertNeeded = {
        Type    = "Choice"
        Choices = [{ Variable = "$.leakage.result.alert", BooleanEquals = true, Next = "SendLeakageAlert" }]
        Default = "Done"
      }

      SendLeakageAlert = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = aws_sns_topic.alerts.arn
          Subject     = "RLI: revenue leakage alert"
          "Message.$" = "$.leakage.result.summary"
        }
        ResultPath = null
        Next       = "Done"
      }

      Done = { Type = "Succeed" }

      NotifyFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn    = aws_sns_topic.alerts.arn
          Subject     = "RLI: daily pipeline FAILED"
          "Message.$" = "States.Format('The daily pipeline stopped. Error: {}. Cause: {}. Execution: {}', $.error.Error, $.error.Cause, $$.Execution.Id)"
        }
        ResultPath = null
        Next       = "PipelineFailed"
      }

      PipelineFailed = { Type = "Fail", Error = "PipelineFailed", Cause = "A stage failed; see the failure email and the execution graph" }
    }
  })
}

output "pipeline_name" {
  value = aws_sfn_state_machine.daily.name
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

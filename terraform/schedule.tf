# ---------------------------------------------------------------------------
# Alarm clock (Phase 5.3): EventBridge Scheduler starts the daily pipeline at 6 am Sydney time.
# Built SWITCHED OFF to keep the cost at US$0. A daily run costs about US$0.10 (mostly Glue).
# To switch it on for a demo:   terraform apply -var="schedule_enabled=true"
# To switch it off again:       terraform apply
# The time zone is part of the schedule, so it follows daylight saving on its own.
# ---------------------------------------------------------------------------

variable "schedule_enabled" {
  description = "Run the daily pipeline automatically every morning (costs about US$3 a month)"
  type        = bool
  default     = false
}

locals {
  schedule_name = "${local.name}-daily-6am"
}

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = local.schedule_name
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "StartOurPipelineOnly"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.daily.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${local.schedule_name}-permissions"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "daily" {
  name        = local.schedule_name
  description = "Start the revenue leakage pipeline every morning before finance logs on"
  state       = var.schedule_enabled ? "ENABLED" : "DISABLED"

  schedule_expression          = "cron(0 6 * * ? *)" # minute hour day month weekday year
  schedule_expression_timezone = "Australia/Sydney"

  flexible_time_window {
    mode = "OFF" # start exactly at 6:00
  }

  target {
    arn      = aws_sfn_state_machine.daily.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({}) # a normal run: the alert line comes from config/alerts.yaml

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600 # if it cannot start within an hour, give up (tomorrow runs anyway)
    }
  }
}

output "schedule_state" {
  value = aws_scheduler_schedule.daily.state
}

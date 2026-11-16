# Event-driven trigger: a new file in raw/ automatically runs the validator.
#   S3 Object Created -> EventBridge rule (raw/ keys only) -> validator Lambda
# Only raw/ is matched, so the validator's own outputs never re-trigger it.
# In Phase 5 this target changes from the Lambda to the Step Functions pipeline.

# 1. Tell S3 to send all its object events to EventBridge
resource "aws_s3_bucket_notification" "to_eventbridge" {
  bucket      = aws_s3_bucket.data.id
  eventbridge = true
}

# 2. A rule that matches only "new file in raw/" events for our bucket
resource "aws_cloudwatch_event_rule" "raw_file_arrived" {
  name        = "${local.name}-raw-file-arrived"
  description = "A new Olist file landed in the raw zone"

  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.data.bucket] }
      object = { key = [{ prefix = "raw/" }] }
    }
  })
}

# 3. Send matching events to the validator Lambda
resource "aws_cloudwatch_event_target" "validator" {
  rule = aws_cloudwatch_event_rule.raw_file_arrived.name
  arn  = aws_lambda_function.validator.arn
}

# 4. Allow EventBridge (and only this rule) to invoke the Lambda
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.validator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.raw_file_arrived.arn
}
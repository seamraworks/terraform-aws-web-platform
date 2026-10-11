# Build alerts/alert-mail.zip with python alerts/package.py before planning.
# This runs outside Lightsail so a stopped or full host can still alert its owner.
locals {
  alert_function = "${var.operations_prefix}-alert-mail"
}

resource "aws_cloudwatch_log_group" "alert_mail" {
  name              = "/aws/lambda/${local.alert_function}"
  retention_in_days = 14
  tags              = local.tags
}

resource "aws_dynamodb_table" "alert_delivery" {
  name         = "${var.operations_prefix}-alert-delivery"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  tags = local.tags
}

# Retain failed events briefly for diagnosis; never put them on the host disk.
resource "aws_sqs_queue" "alert_failures" {
  name                      = "${var.operations_prefix}-alert-failures"
  message_retention_seconds = 86400
  sqs_managed_sse_enabled   = true
  tags                      = local.tags
}
resource "aws_sqs_queue_policy" "alert_failures" {
  queue_url = aws_sqs_queue.alert_failures.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "sns.amazonaws.com" },
    Action = "sqs:SendMessage", Resource = aws_sqs_queue.alert_failures.arn,
    Condition = {
      ArnEquals    = { "aws:SourceArn" = aws_sns_topic.operations.arn },
      StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
    }
  }] })
}

resource "aws_iam_role" "alert_mail" {
  name = local.alert_function
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" },
    Action = "sts:AssumeRole"
  }] })
  tags = local.tags
}
resource "aws_iam_role_policy" "alert_mail" {
  role = aws_iam_role.alert_mail.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"],
    Resource = "${aws_cloudwatch_log_group.alert_mail.arn}:*" },
    { Effect   = "Allow", Action = ["ses:SendEmail"],
      Resource = [var.ses_identity_arn, var.ses_configuration_set_arn],
      Condition = {
        StringEquals                = { "ses:FromAddress" = var.email_from },
        "ForAllValues:StringEquals" = { "ses:Recipients" = [var.owner_email] }
    } },
    { Effect = "Allow", Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem"],
    Resource = aws_dynamodb_table.alert_delivery.arn },
    { Effect = "Allow", Action = ["cloudwatch:DescribeAlarms"], Resource = aws_cloudwatch_metric_alarm.health.arn },
    { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.alert_failures.arn }
  ] })
}

resource "aws_lambda_function" "alert_mail" {
  function_name                  = local.alert_function
  role                           = aws_iam_role.alert_mail.arn
  filename                       = data.archive_file.alert_mail.output_path
  source_code_hash               = data.archive_file.alert_mail.output_base64sha256
  runtime                        = "python3.13"
  handler                        = "handler.handler"
  timeout                        = 30
  memory_size                    = 128
  reserved_concurrent_executions = 2
  environment {
    variables = {
      ALERT_TO         = var.owner_email
      EMAIL_FROM       = var.email_from
      BRAND_NAME       = var.brand_name
      TIMEZONE         = var.timezone
      ALERT_TOPIC_ARN  = aws_sns_topic.operations.arn
      HEALTH_ALARM_ARN = aws_cloudwatch_metric_alarm.health.arn
      DELIVERY_TABLE   = aws_dynamodb_table.alert_delivery.name
    }
  }
  tags       = local.tags
  depends_on = [aws_iam_role_policy.alert_mail]
}
resource "aws_lambda_function_event_invoke_config" "alert_mail" {
  function_name                = aws_lambda_function.alert_mail.function_name
  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2
  destination_config {
    on_failure { destination = aws_sqs_queue.alert_failures.arn }
  }
}
resource "aws_lambda_permission" "alert_mail" {
  statement_id   = "OperationsSNS"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.alert_mail.function_name
  principal      = "sns.amazonaws.com"
  source_arn     = aws_sns_topic.operations.arn
  source_account = data.aws_caller_identity.current.account_id
}
resource "aws_sns_topic_subscription" "alert_mail" {
  topic_arn           = aws_sns_topic.operations.arn
  protocol            = "lambda"
  endpoint            = aws_lambda_function.alert_mail.arn
  filter_policy_scope = "MessageBody"
  filter_policy       = jsonencode({ AlarmName = [aws_cloudwatch_metric_alarm.health.alarm_name] })
  redrive_policy      = jsonencode({ deadLetterTargetArn = aws_sqs_queue.alert_failures.arn })
  depends_on = [aws_lambda_permission.alert_mail, aws_lambda_function_event_invoke_config.alert_mail,
    aws_sqs_queue_policy.alert_failures, aws_cloudwatch_metric_alarm.alert_delivery_errors,
  aws_cloudwatch_metric_alarm.alert_undelivered]
}

# Raw SNS fallback bypasses Lambda and SES. Filtering prevents a notification
# failure from recursively invoking the formatter that just failed.
resource "aws_cloudwatch_metric_alarm" "alert_delivery_errors" {
  alarm_name          = "${var.operations_prefix}-alert-delivery-errors"
  alarm_description   = "Readable comment alerts failed or were throttled. Check the ${var.operations_prefix}-alert-mail Lambda logs and the ${var.operations_prefix}-health alarm. This fallback uses SNS directly; it does not depend on SES or the comment host."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  metric_query {
    id          = "failures"
    expression  = "errors + throttles"
    label       = "Alert delivery failures"
    return_data = true
  }
  dynamic "metric_query" {
    for_each = { errors = "Errors", throttles = "Throttles" }
    content {
      id = metric_query.key
      metric {
        namespace   = "AWS/Lambda"
        metric_name = metric_query.value
        dimensions  = { FunctionName = local.alert_function }
        period      = 60
        stat        = "Sum"
      }
    }
  }
  alarm_actions = [aws_sns_topic.operations.arn]
  tags          = local.tags
}
resource "aws_cloudwatch_metric_alarm" "alert_undelivered" {
  alarm_name          = "${var.operations_prefix}-alert-undelivered"
  alarm_description   = "A comment health alert could not be delivered after retries. Check the ${var.operations_prefix}-alert-failures SQS queue, Lambda delivery configuration, and ${var.operations_prefix}-health alarm. This fallback uses SNS directly."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.alert_failures.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  tags                = local.tags
}

data "archive_file" "alert_mail" {
  type             = "zip"
  source_file      = "${path.module}/alerts/handler.py"
  output_path      = "${path.root}/.build/${var.name}-alert-mail.zip"
  output_file_mode = "0644"
}

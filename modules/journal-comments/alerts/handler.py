"""CloudWatch -> SNS -> readable SES alert, independent of the comment host."""
import datetime as dt
from html import escape
import hashlib
import json
import os
import time
import urllib.parse
from zoneinfo import ZoneInfo


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Alarm timestamp must include a timezone")
    return result


def render(message, region):
    state = message["NewStateValue"]
    if state not in {"ALARM", "OK"}:
        raise ValueError("Unsupported alarm state")
    test = message.get("Test") is True
    recovered = state == "OK"
    heading = "Comments health checks recovered" if recovered else "Comments need attention"
    subject = os.environ.get("BRAND_NAME", "Website") + ": " + heading
    if test:
        subject = "TEST — " + subject
    when = timestamp(message["StateChangeTime"]).astimezone(ZoneInfo(os.environ.get("TIMEZONE", "UTC")))
    when = when.strftime("%d %B %Y at %H:%M:%S %Z")
    reason = str(message.get("NewStateReason", "No additional detail supplied."))[:4000]
    missing = any(word in reason.lower() for word in ("missing", "unknown", "not received", "no datapoints", "no data points"))
    if recovered:
        explanation = "The background health monitor is reporting healthy again."
        impact = "Moderation is running, storage is within its healthy range, and the comment sweep and backup are within their allowed age. This is a background health check, not a test of every login or email delivery."
        action = "No immediate action is needed. If these alerts keep alternating, check the service status for an intermittent problem."
    else:
        explanation = ("AWS has stopped receiving the regular health heartbeat. The host, worker or heartbeat delivery may have stopped."
                       if missing else "The background health monitor reported a problem for three consecutive five-minute periods.")
        impact = "Spam checks or backups may be delayed. A storage safety pause can also make comments unavailable. The main website is hosted separately."
        action = "Connect to the comment host and run sudo comments status. Check the worker, disk/inode usage, storage monitor, recovery pause, and the latest successful sweep and backup."
    limits = "Healthy means: moderation is not paused, the disk monitor is current, log rotation is working, disk and inode use are below 80% with at least 2 GiB free, the sweep is under 2 hours old, and the backup is under 26 hours old. A missing heartbeat also triggers the alert."
    link = (f"https://{region}.console.aws.amazon.com/cloudwatch/home?region={region}"
            "#alarmsV2:alarm/" + urllib.parse.quote(message["AlarmName"], safe=""))
    test_note = "Delivery test only. This message does not indicate an actual outage or recovery." if test else ""
    plain = "\n\n".join(filter(None, [heading, test_note, when, explanation,
        "What this means\n" + impact, "What to do\n" + action,
        "Open the AWS health alarm\n" + link,
        "What is monitored\n" + limits, "AWS diagnostic detail\n" + reason]))
    color = "#18734b" if recovered else "#b54708"
    label = "RECOVERED" if recovered else "NEEDS ATTENTION"
    if test:
        label = "DELIVERY TEST · " + label
    html = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#f3f5f7;color:#243047;font:16px/1.6 Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:100%;max-width:640px;background:#fff;border:1px solid #dfe5eb;border-radius:12px"><tr><td style="padding:32px">
<div style="font-size:13px;color:#536278">SIMPLE JAVA MAIL · COMMENT OPERATIONS</div>
<p style="font-size:12px;font-weight:bold;letter-spacing:1px;color:{color}">{label}</p>
<h1 style="margin:12px 0;font-size:28px;line-height:1.25;color:#18273c">{heading}</h1>
<p style="font-size:13px;color:#65748a">{escape(when)}</p>
{f'<p style="padding:12px;background:#eef3fa;border-radius:6px"><strong>{test_note}</strong></p>' if test else ''}
<p>{escape(explanation)}</p>
<h2 style="font-size:18px;margin-top:24px">What this means</h2><p>{escape(impact)}</p>
<h2 style="font-size:18px;margin-top:24px">What to do</h2><p>{escape(action)}</p>
<p style="margin:24px 0"><a href="{escape(link, quote=True)}" style="display:inline-block;padding:12px 18px;background:#254e85;color:#fff;text-decoration:none;border-radius:6px">Open the AWS health alarm</a></p>
<div style="border-top:1px solid #e1e6ed;padding-top:16px;font-size:13px;color:#65748a"><strong>What is monitored</strong><p>{escape(limits)}</p>
<strong>AWS diagnostic detail</strong><p style="white-space:pre-wrap;overflow-wrap:anywhere">{escape(reason)}</p></div>
</td></tr></table></td></tr></table></body></html>'''
    return subject, plain, html


def deliver(message, *, ses, table, cloudwatch, now=None):
    """Lease a transition so SNS retries/concurrent deliveries do not resend it."""
    now = int(time.time() if now is None else now)
    changed = timestamp(message["StateChangeTime"])
    key = hashlib.sha256((message["AlarmArn"] + "|" + message["NewStateValue"]
                          + "|" + changed.isoformat()).encode()).hexdigest()
    # CloudWatch/SNS can deliver transitions out of order. Do not send an old
    # ALARM after recovery (or an old OK during a new outage).
    if message.get("Test") is not True:
        alarms = cloudwatch.describe_alarms(AlarmNames=[message["AlarmName"]])["MetricAlarms"]
        if not alarms:
            raise RuntimeError("Health alarm unavailable")
        current = alarms[0]
        if current["StateUpdatedTimestamp"] > changed:
            return "obsolete"
    try:
        table.put_item(Item={"id": key, "lease_until": now + 120, "expires_at": now + 604800},
            ConditionExpression="attribute_not_exists(id) OR (attribute_not_exists(delivered) AND lease_until < :now)",
            ExpressionAttributeValues={":now": now})
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing = table.get_item(Key={"id": key}, ConsistentRead=True).get("Item", {})
        if existing.get("delivered"):
            return "duplicate"
        raise RuntimeError("Another delivery holds the lease") from exc
    subject, plain, html = render(message, os.environ["AWS_REGION"])
    try:
        result = ses.send_email(Source=os.environ.get('BRAND_NAME', 'Website') + ' comments <' + os.environ['EMAIL_FROM'] + '>',
            Destination={"ToAddresses": [os.environ["ALERT_TO"]]},
            Message={"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": {
                "Text": {"Data": plain, "Charset": "UTF-8"},
                "Html": {"Data": html, "Charset": "UTF-8"}}})
    except Exception:
        # A failed send must remain retryable; do not mark the mail delivered.
        table.delete_item(Key={"id": key})
        raise
    table.update_item(Key={"id": key}, UpdateExpression="SET delivered = :yes, message_id = :message",
        ExpressionAttributeValues={":yes": True, ":message": result["MessageId"]})
    return "sent"


def handler(event, context):
    import boto3
    from botocore.config import Config
    options = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
    ses = boto3.client("ses", config=options)
    cloudwatch = boto3.client("cloudwatch", config=options)
    table = boto3.resource("dynamodb", config=options).Table(os.environ["DELIVERY_TABLE"])
    results = []
    for record in event["Records"]:
        sns = record["Sns"]
        if record.get("EventSource") != "aws:sns" or sns["TopicArn"] != os.environ["ALERT_TOPIC_ARN"]:
            raise ValueError("Unexpected notification source")
        message = json.loads(sns["Message"])
        if message.get("AlarmArn") != os.environ["HEALTH_ALARM_ARN"]:
            raise ValueError("Unexpected alarm")
        if message.get("NewStateValue") not in {"ALARM", "OK"}:
            raise ValueError("Unexpected state")
        outcome = deliver(message, ses=ses, table=table, cloudwatch=cloudwatch)
        # Never log a raw notification, comment, credential or email body.
        print(json.dumps({"state": message["NewStateValue"], "outcome": outcome,
                          "test": message.get("Test") is True}))
        results.append(outcome)
    return {"deliveries": results}

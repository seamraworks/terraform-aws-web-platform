import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

source = Path(__file__).resolve().parents[3] / "modules/journal-comments/alerts/handler.py"
spec = importlib.util.spec_from_file_location("alert_handler", source)
alerts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alerts)

ARN = "arn:aws:cloudwatch:eu-central-1:123456789012:alarm:web-comments-health"
TOPIC = "arn:aws:sns:eu-central-1:123456789012:web-comments-operations"


def message(state="ALARM", **extra):
    return {"AlarmName": "web-comments-health", "AlarmArn": ARN,
            "NewStateValue": state, "OldStateValue": "OK" if state == "ALARM" else "ALARM",
            "StateChangeTime": "2026-10-06T07:00:00.000Z",
            "NewStateReason": "Threshold Crossed: 3 datapoints were below 1.", **extra}


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Table:
    def __init__(self):
        self.rows = {}

    def put_item(self, Item, **kwargs):
        row = self.rows.get(Item["id"])
        if row and (row.get("delivered") or row["lease_until"] >= kwargs["ExpressionAttributeValues"][":now"]):
            raise ConditionalFailure()
        self.rows[Item["id"]] = dict(Item)

    def get_item(self, Key, **kwargs):
        return {"Item": self.rows.get(Key["id"], {})}

    def delete_item(self, Key):
        self.rows.pop(Key["id"], None)

    def update_item(self, Key, ExpressionAttributeValues, **kwargs):
        self.rows[Key["id"]].update(delivered=True, message_id=ExpressionAttributeValues[":message"])


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"AWS_REGION": "eu-central-1",
            "ALERT_TO": "owner@example.com", "EMAIL_FROM": "comments@example.com", "BRAND_NAME": "Example Website", "TIMEZONE": "Europe/Amsterdam", "ALERT_TOPIC_ARN": TOPIC,
            "HEALTH_ALARM_ARN": ARN, "DELIVERY_TABLE": "test-deliveries"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.ses = Mock()
        self.ses.send_email.return_value = {"MessageId": "ses-1"}
        self.table = Table()
        self.cloudwatch = Mock()
        self.cloudwatch.describe_alarms.return_value = {"MetricAlarms": [{
            "StateUpdatedTimestamp": alerts.timestamp("2026-10-06T07:00:00Z")} ]}

    def deliver(self, payload=None, now=100):
        return alerts.deliver(payload or message(), ses=self.ses, table=self.table,
                              cloudwatch=self.cloudwatch, now=now)

    def test_alarm_is_actionable_and_does_not_claim_a_specific_failure(self):
        subject, plain, html = alerts.render(message(), "eu-central-1")
        self.assertEqual("Example Website: Comments need attention", subject)
        self.assertIn("sudo comments status", plain)
        self.assertIn("may be delayed", plain)
        self.assertIn("three consecutive five-minute", plain)
        self.assertIn("09:00:00 CEST", plain)
        self.assertIn("What to do", html)
        self.assertIn("alarmsV2:alarm/web-comments-health", html)

    def test_recovery_is_specific_about_what_is_healthy(self):
        subject, plain, html = alerts.render(message("OK"), "eu-central-1")
        self.assertIn("recovered", subject)
        self.assertIn("No immediate action", plain)
        self.assertIn("not a test of every login", plain)
        self.assertIn("RECOVERED", html)

    def test_missing_heartbeat_and_test_label(self):
        subject, plain, html = alerts.render(message(Test=True,
            NewStateReason="3 datapoints were missing"), "eu-central-1")
        self.assertTrue(subject.startswith("TEST"))
        self.assertIn("does not indicate an actual outage", plain)
        self.assertIn("stopped receiving", plain)
        self.assertIn("DELIVERY TEST", html)

    def test_escape_diagnostics_and_reject_invalid_states(self):
        _, plain, html = alerts.render(message(NewStateReason='<script>alert("x")</script>'), "eu-central-1")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<script>", plain)
        with self.assertRaises(ValueError):
            alerts.render(message("INSUFFICIENT_DATA"), "eu-central-1")

    def test_send_has_plain_html_and_retry_is_deduplicated(self):
        self.assertEqual("sent", self.deliver())
        self.assertEqual("duplicate", self.deliver())
        self.ses.send_email.assert_called_once()
        body = self.ses.send_email.call_args.kwargs["Message"]["Body"]
        self.assertEqual({"Text", "Html"}, set(body))
        self.assertEqual("UTF-8", body["Html"]["Charset"])

    def test_failed_ses_send_releases_lease_for_retry(self):
        self.ses.send_email.side_effect = RuntimeError("Delivery unavailable")
        with self.assertRaises(RuntimeError):
            self.deliver()
        self.assertEqual({}, self.table.rows)
        self.ses.send_email.side_effect = None
        self.assertEqual("sent", self.deliver())

    def test_concurrent_delivery_retries_and_expired_lease_can_send(self):
        self.table.update_item = Mock(side_effect=RuntimeError("After-send record failure"))
        with self.assertRaises(RuntimeError):
            self.deliver()
        with self.assertRaisesRegex(RuntimeError, "holds the lease"):
            self.deliver(now=150)
        self.table.update_item = Mock()
        self.assertEqual("sent", self.deliver(now=221))

    def test_old_state_after_new_transition_is_skipped(self):
        self.cloudwatch.describe_alarms.return_value["MetricAlarms"][0]["StateUpdatedTimestamp"] = alerts.timestamp("2026-10-06T07:05:00Z")
        self.assertEqual("obsolete", self.deliver())
        self.ses.send_email.assert_not_called()

    def test_dst_in_winter_and_naive_timestamp_rejected(self):
        _, plain, _ = alerts.render(message(StateChangeTime="2026-12-06T07:00:00Z"), "eu-central-1")
        self.assertIn("08:00:00 CET", plain)
        with self.assertRaises(ValueError):
            alerts.timestamp("2026-10-06T07:00:00")

    def test_handler_rejects_foreign_source_and_foreign_alarm(self):
        boto3 = ModuleType("boto3")
        boto3.client, boto3.resource = Mock(), Mock()
        config = ModuleType("botocore.config")
        config.Config = Mock()
        event = {"Records": [{"EventSource": "aws:sns", "Sns": {
            "TopicArn": "foreign", "Message": json.dumps(message())}}]}
        with patch.dict(sys.modules, {"boto3": boto3, "botocore.config": config}):
            with self.assertRaisesRegex(ValueError, "source"):
                alerts.handler(event, None)
            event["Records"][0]["Sns"]["TopicArn"] = TOPIC
            event["Records"][0]["Sns"]["Message"] = json.dumps(message(AlarmArn="foreign"))
            with self.assertRaisesRegex(ValueError, "alarm"):
                alerts.handler(event, None)


if __name__ == "__main__":
    unittest.main()

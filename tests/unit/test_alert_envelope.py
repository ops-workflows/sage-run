"""Deterministic alert envelope and coalescing identity tests."""

from __future__ import annotations

from shared.lib.alert_envelope import parse_alert_envelope


def test_aws_state_transitions_share_coalesce_key() -> None:
    firing = parse_alert_envelope(
        """Status: firing
Alertname: production-api-gatewayAlarm
Labels: alertarn=arn:aws:cloudwatch:eu-west-1:123456789012:alarm:production-api-gatewayAlarm, environment=production
"""
    )
    recovery = parse_alert_envelope(
        """Status: resolved
Alertname: production-api-gatewayAlarm
Labels: alertarn=arn:aws:cloudwatch:eu-west-1:123456789012:alarm:production-api-gatewayAlarm, environment=production
"""
    )

    assert firing is not None
    assert recovery is not None
    assert firing.state == "firing"
    assert recovery.state == "recovery"
    assert firing.account == "123456789012"
    assert firing.region == "eu-west-1"
    assert firing.environment == "production"
    assert firing.coalesce_key("alert-triage") == recovery.coalesce_key("alert-triage")


def test_splunk_dispatch_ids_do_not_change_coalesce_key() -> None:
    first = parse_alert_envelope(
        "Splunk alert: Online-UI-API errors (https://splunk.example/app/search/@go?sid=scheduler__one)"
    )
    second = parse_alert_envelope(
        "Splunk alert: Online-UI-API errors (https://splunk.example/app/search/@go?sid=scheduler__two)"
    )

    assert first is not None
    assert second is not None
    assert first.identity == "Online-UI-API errors"
    assert first.coalesce_key("alert-triage") == second.coalesce_key("alert-triage")


def test_unsupported_message_has_no_alert_identity() -> None:
    assert parse_alert_envelope("@agent investigate this manually") is None


def test_gcp_alert_identity_uses_policy_and_project() -> None:
    def body(incident: str, state: str) -> str:
        return (
            "Incident open on policy Cloud Run 5xx responses alert (prod)\n"
            "##### [[ALERT - Error] [online-api][prod] Cloud Run 5xx responses](https://console.cloud.google.com/"
            f"monitoring/alerting/alerts/{incident}?project=example-prod-1234)\n"
            "Summary: Cloud Run 5xx responses is above the threshold of 0.000 with a value of 1.000.\n"
            "Policy: Cloud Run 5xx responses alert (prod)\n"
            "Project: example-prod-1234\n"
            f"State: {state}\n"
            "Severity: Error\n"
            "application: online-api\n"
            "environment: prod"
        )

    first = parse_alert_envelope(body("0.first", "open"))
    second = parse_alert_envelope(body("0.second", "closed"))

    assert first is not None
    assert second is not None
    assert first.source == "gcp"
    assert first.identity == "Cloud Run 5xx responses alert (prod)"
    assert first.account == "example-prod-1234"
    assert first.environment == "prod"
    assert first.state == "firing"
    assert second.state == "recovery"
    assert first.coalesce_key("alert-triage") == second.coalesce_key("alert-triage")

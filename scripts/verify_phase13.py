"""Validate notification release boundaries and strict API/policy consistency."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
catalog = ROOT / "packages/source-catalog/notifications.json"
embedded = ROOT / "services/api/internal/notifications/policy.json"
assert catalog.read_bytes() == embedded.read_bytes()
policy = json.loads(catalog.read_text())
assert policy["scientific_alerts_approved"] is False
assert policy["recovery_confirmations"] == 2 and policy["delivery_attempts"] == 5
assert policy["channels"] == ["in_app", "email"]
assert policy["evidence_bytes"] == 32768
product = json.loads((ROOT / "packages/source-catalog/product.json").read_text())
assert product["production_approved"] is False
assert not product["export_permissions"]["source_forecast_rows"]
assert not product["export_permissions"]["source_advisory_content"]
assert (ROOT / "packages/source-catalog/product.json").read_bytes() == (
    ROOT / "services/api/internal/product/policy.json"
).read_bytes()
api = json.loads((ROOT / "packages/schemas/product.openapi.json").read_text())
for path, method in [
    ("/notification-status", "get"),
    ("/notification-settings", "get"),
    ("/notification-email", "post"),
    ("/notification-email", "delete"),
    ("/notification-email/verify", "post"),
    ("/notification-evidence/{sha}", "get"),
    ("/alerts/{id}/replay", "post"),
    ("/alerts/{id}/retry-email", "post"),
]:
    operation = api["paths"][path][method]
    assert operation["security"] == [{"SessionBearer": []}]
    if method != "get":
        assert {p["name"] for p in operation["parameters"]} >= {
            "Origin",
            "X-CSRF-Token",
            "Idempotency-Key",
        }
for variant in api["components"]["schemas"]["AlertRule"]["oneOf"]:
    assert variant["properties"]["channel"]["enum"] == ["in_app", "email", "both"]
    assert variant["properties"]["cooldown_minutes"]["maximum"] == 1440
print(
    "Notification contracts passed: policy pins, strict ownership/CSRF, bounded channels and scientific/redistribution gates."
)

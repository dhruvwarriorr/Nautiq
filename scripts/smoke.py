"""Verify Phase 1 through the externally exposed web and API."""
import json
import os
import time
import urllib.error
import urllib.request

api = f"http://127.0.0.1:{os.environ.get('API_PORT', '8080')}"
web = f"http://127.0.0.1:{os.environ.get('WEB_PORT', '3000')}"
names = {
    "postgresql", "postgis", "timescaledb", "schema", "minio", "redis",
    "nats_jetstream", "ml_inference", "field_service", "web",
}
for attempt in range(60):
    try:
        with urllib.request.urlopen(f"{api}/api/v1/health", timeout=6) as response:
            report = json.load(response)
        assert report["status"] == "healthy", report
        assert names <= report["dependencies"].keys(), report
        assert all(report["dependencies"][name]["status"] == "healthy" for name in names)
        break
    except (OSError, AssertionError) as error:
        if attempt == 59:
            raise SystemExit(f"Platform did not become healthy: {error}") from error
        time.sleep(2)
with urllib.request.urlopen(f"{web}/status", timeout=10) as response:
    html = response.read().decode()
assert "Services are connected." in html
assert "Source health" in html
assert "Public production and scientific approval remain unavailable" in html
with urllib.request.urlopen(f"{api}/health/ready", timeout=5) as response:
    ready = json.load(response)
assert ready["status"] == "healthy"
assert set(ready["dependencies"]) == {"postgresql", "postgis", "timescaledb", "schema"}
with urllib.request.urlopen(f"{api}/api/v1/capabilities", timeout=5) as response:
    capabilities = json.load(response)["capabilities"]
assert capabilities["platform_runtime"]
assert not any(value for name, value in capabilities.items() if name not in {"platform_runtime", "observations", "climatology", "expected_state", "ml_residual", "predictive_intervals", "calibrated_uncertainty", "profile_anomaly_diagnostics", "field_sampling", "event_detection_diagnostics", "advisory_diagnostics", "trip_diagnostics"})
print(f"All {len(names)} dependency checks passed. Health page: {web}/status")

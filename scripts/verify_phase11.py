"""Release policy consistency and explicit absence of unreviewed numeric limits."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
policy = json.loads((ROOT / "packages/source-catalog/trips.json").read_text())
assert (ROOT / "packages/source-catalog/trips.json").read_bytes() == (
    ROOT / "services/api/internal/trips/policy.json"
).read_bytes()
assert policy["approved"] is False and policy["review_record"] == ""
assert all(
    s["caution"] is None and s["critical"] is None and s["origin"] == "unreviewed"
    for s in policy["inputs"]
)
assert policy["combinations"] == [] and policy["deterioration"] == []
assert policy["inequality"] == "value >= limit"
assert {s["variable"] for s in policy["inputs"]} == {
    "wave_height_m",
    "wind_speed_m_s",
    "current_speed_m_s",
}
print(
    "Trip release contract passed: embedded policy matches catalog, no unreviewed numeric limits and explicit approval gate."
)

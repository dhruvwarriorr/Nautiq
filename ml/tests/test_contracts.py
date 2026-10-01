import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def test_planned_profile_contract_schema_is_valid_and_null_is_explicit():
    contract = json.loads((ROOT / "packages/schemas/profiles.openapi.json").read_text())
    for schema in contract["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)
    problem = contract["components"]["schemas"]["Problem"]
    Draft202012Validator(problem).validate(
        {
            "type": "about:blank",
            "title": "Unavailable",
            "status": 503,
            "code": "capability_unavailable",
            "request_id": "req_fixture",
        }
    )
    assert (
        contract["components"]["schemas"]["ProfilePage"]["properties"]["items"][
            "maxItems"
        ]
        == 200
    )

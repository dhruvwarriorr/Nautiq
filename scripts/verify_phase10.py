"""Offline official CAP identity, geometry, validity and adversarial input contracts."""

from copy import deepcopy
from nautiq_ml.advisories.core import parse, feed, cap_url, lifecycle, AdvisoryError


def fixture(
    identifier="fixture",
    msg_type="Alert",
    refs="",
    sender="IMD",
    geometry="<polygon>10,70 10,71 11,71 11,70 10,70</polygon>",
    sent="2026-10-03T00:00:00Z",
    infos=True,
):
    return f"""<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2"><identifier>{identifier}</identifier><sender>{sender}</sender><sent>{sent}</sent><status>Actual</status><msgType>{msg_type}</msgType><scope>Public</scope><references>{refs}</references>{f"<info><language>en-IN</language><category>Met</category><event>High waves</event><urgency>Expected</urgency><severity>Severe</severity><certainty>Likely</certainty><effective>2026-10-03T00:00:00Z</effective><expires>2026-10-04T00:00:00Z</expires><area><areaDesc>Official area</areaDesc>{geometry}</area></info>" if infos else ""}</alert>""".encode()


def refuses(fn):
    try:
        fn()
    except (ValueError, AdvisoryError):
        return
    raise AssertionError("unsupported advisory input accepted")


def main():
    as_of = "2026-10-03T02:00:00Z"
    a = parse(fixture(), as_of)
    assert a["infos"][0]["areas"][0]["polygons"][0]["coordinates"][0][0] == [70.0, 10.0]
    assert a["infos"][0]["effective"] == "2026-10-03T00:00:00Z"
    circle = parse(fixture(geometry="<circle>12,72 25</circle>"), as_of)
    assert circle["infos"][0]["areas"][0]["circles"] == [
        {"center": [72.0, 12.0], "radius_km": 25.0}
    ]
    unknown = parse(
        fixture(
            geometry="<geocode><valueName>district</valueName><value>42</value></geocode>"
        ),
        as_of,
    )
    assert unknown["infos"][0]["areas"][0]["unresolved"] == ["unmapped_geocode"]
    invalid = parse(
        fixture(geometry="<polygon>10,70 11,71 10,71 11,70 10,70</polygon>"), as_of
    )
    assert invalid["infos"][0]["areas"][0]["unresolved"]
    missing = parse(
        fixture().replace(b"<expires>2026-10-04T00:00:00Z</expires>", b""), as_of
    )
    assert "unknown_or_invalid_validity" in missing["infos"][0]["issues"]
    reversed_time = parse(
        fixture().replace(b"2026-10-04T00:00:00Z", b"2026-10-02T00:00:00Z"), as_of
    )
    assert reversed_time["infos"][0]["issues"]
    a["revision_id"] = "a"
    update = parse(
        fixture(
            "update",
            "Update",
            "IMD,fixture,2026-10-03T00:00:00Z",
            sent="2026-10-03T01:00:00Z",
        ),
        as_of,
    )
    update["revision_id"] = "b"
    cancel = parse(
        fixture(
            "cancel",
            "Cancel",
            "IMD,update,2026-10-03T01:00:00Z",
            sent="2026-10-03T02:00:00Z",
            infos=False,
        ),
        as_of,
    )
    cancel["revision_id"] = "c"
    forward = lifecycle([a, update, cancel])
    backward = lifecycle([cancel, update, a])
    assert forward == backward
    assert (
        forward["a"]["state"] == "superseded" and forward["b"]["state"] == "cancelled"
    )
    assert lifecycle([a])["a"]["state"] == "active"  # Feed absence never cancels.
    hostile = deepcopy(cancel)
    hostile["sender"] = "attacker"
    assert lifecycle([update, hostile])["b"]["state"] == "active"
    bad = deepcopy(update)
    bad["infos"][0]["areas"][0]["unresolved"] = ["text_only"]
    assert lifecycle([a, bad])["a"]["state"] == "active"
    collision = deepcopy(a)
    collision["revision_id"] = "collision"
    life = lifecycle([a, collision, update])
    assert life["a"]["state"] == "active" and "identity_conflict" in life["a"]["issues"]
    private = parse(
        fixture().replace(b"<scope>Public</scope>", b"<scope>Private</scope>"), as_of
    )
    assert not private["operational"]
    test = parse(
        fixture().replace(b"<status>Actual</status>", b"<status>Test</status>"), as_of
    )
    assert not test["operational"]
    english = fixture().replace(
        b"</alert>",
        b"<info><language>hi-IN</language><category>Met</category><event>Storm</event><urgency>Expected</urgency><severity>Severe</severity><certainty>Likely</certainty></info></alert>",
    )
    assert len(parse(english, as_of)["infos"]) == 2
    for raw in (
        b'<!DOCTYPE alert [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + fixture(),
        fixture().replace(
            b"<sent>2026-10-03T00:00:00Z</sent>", b"<sent>2026-10-03T00:00:00</sent>"
        ),
        fixture().replace(
            b"<identifier>fixture</identifier>",
            b"<identifier>fixture</identifier><identifier>other</identifier>",
        ),
    ):
        refuses(lambda raw=raw: parse(raw, as_of))
    for url in (
        "https://attacker.invalid/cap_public_website/FetchXMLFile?identifier=1",
        "https://sachet.ndma.gov.in:443/cap_public_website/FetchXMLFile?identifier=1",
        "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=1&identifier=2",
        "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=1#x",
    ):
        refuses(lambda url=url: cap_url(url))
    rss = b'<rss version="2.0"><channel><item><link>https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier=1</link></item></channel></rss>'
    assert len(feed(rss)) == 1
    refuses(
        lambda: feed(
            rss.replace(
                b"</channel>",
                rss[rss.index(b"<item>") : rss.index(b"</item>") + 7] + b"</channel>",
            )
        )
    )
    print(
        "Official CAP offline contracts passed: coordinates, circles, ambiguity, validity, revisions, languages, public/test and XML/URL bounds."
    )


if __name__ == "__main__":
    main()

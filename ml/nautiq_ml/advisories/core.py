"""Bounded CAP 1.2 parser. Preserve ambiguity instead of manufacturing clear weather."""

import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from shapely.geometry import Polygon, mapping

from ..fields.core import canonical

POLICY = json.loads(
    next(
        p
        for p in (
            Path("/advisories.json"),
            Path(__file__).parents[3] / "packages/source-catalog/advisories.json",
        )
        if p.exists()
    ).read_text()
)
METHOD = POLICY["method"]
NS = "{urn:oasis:names:tc:emergency:cap:1.2}"


class AdvisoryError(ValueError):
    pass


def utc(value):
    if not isinstance(value, str) or len(value) > 64:
        raise AdvisoryError("invalid_cap_time")
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise AdvisoryError("invalid_cap_time") from e
    if t.tzinfo is None:
        raise AdvisoryError("timezone_required")
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def xml(data, feed=False):
    if not data or len(data) > POLICY["limits"]["feed_bytes" if feed else "xml_bytes"]:
        raise AdvisoryError("xml_byte_budget")
    # Reject UTF-16/32, DTDs and entity declarations before the standard parser.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as e:
        raise AdvisoryError("xml_utf8_required") from e
    if "\x00" in text or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise AdvisoryError("xml_external_entities_forbidden")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise AdvisoryError("invalid_xml") from e
    if len(list(root.iter())) > POLICY["limits"]["xml_nodes"]:
        raise AdvisoryError("xml_node_budget")
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > 16 or len(node.text or "") > 65536:
            raise AdvisoryError("xml_depth_or_text_budget")
        stack.extend((child, depth + 1) for child in node)
    return root


def cap_url(value):
    u = urlsplit(value)
    if (
        u.scheme != "https"
        or u.netloc != "sachet.ndma.gov.in"
        or u.fragment
        or u.path != "/cap_public_website/FetchXMLFile"
    ):
        raise AdvisoryError("cap_url_not_allowlisted")
    q = parse_qs(u.query, strict_parsing=True)
    if (
        set(q) != {"identifier"}
        or len(q["identifier"]) != 1
        or not re.fullmatch(r"[0-9]{1,30}", q["identifier"][0])
    ):
        raise AdvisoryError("cap_identifier_invalid")
    return (
        "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile?identifier="
        + q["identifier"][0]
    )


def feed(data):
    root = xml(data, True)
    if (
        root.tag != "rss"
        or root.attrib.get("version") != "2.0"
        or len(root.findall("channel")) != 1
    ):
        raise AdvisoryError("rss_2_required")
    items = root.findall("channel/item")
    if len(items) > POLICY["limits"]["feed_items"]:
        raise AdvisoryError("feed_item_budget_no_truncation")
    urls = []
    for item in items:
        links = item.findall("link")
        if len(links) != 1:
            raise AdvisoryError("rss_link_required")
        url = cap_url(links[0].text or "")
        if url in urls:
            raise AdvisoryError("duplicate_rss_identity")
        urls.append(url)
    return urls


def text(node, name, required=False):
    values = node.findall(NS + name)
    if len(values) > 1 or (
        required and (not values or not (values[0].text or "").strip())
    ):
        raise AdvisoryError("missing_or_duplicate_" + name)
    return (values[0].text or "").strip() if values else None


def coordinate(pair):
    parts = pair.split(",")
    if len(parts) != 2:
        raise AdvisoryError("invalid_cap_coordinate")
    lat, lon = map(float, parts)
    if not math.isfinite(lat + lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise AdvisoryError("invalid_cap_coordinate")
    return [lon, lat]


def area(node):
    result = {
        "description": text(node, "areaDesc", True),
        "polygons": [],
        "circles": [],
        "geocodes": [],
        "unresolved": [],
    }
    for n in node.findall(NS + "polygon"):
        try:
            points = [coordinate(p) for p in (n.text or "").split()]
            if (
                not 4 <= len(points) <= POLICY["limits"]["vertices"]
                or points[0] != points[-1]
                or any(abs(a[0] - b[0]) > 180 for a, b in zip(points, points[1:]))
            ):
                raise AdvisoryError("invalid_or_dateline_polygon")
            p = Polygon(points)
            if not p.is_valid or p.is_empty or p.area == 0:
                raise AdvisoryError("invalid_polygon")
            result["polygons"].append(mapping(p))
        except (ValueError, OverflowError):
            result["unresolved"].append("invalid_polygon")
    for n in node.findall(NS + "circle"):
        try:
            parts = (n.text or "").split()
            if len(parts) != 2:
                raise AdvisoryError("invalid_circle")
            point = coordinate(parts[0])
            radius = float(parts[1])
            if not math.isfinite(radius) or not 0 <= radius <= 20000:
                raise AdvisoryError("invalid_circle")
            result["circles"].append({"center": point, "radius_km": radius})
        except (ValueError, OverflowError):
            result["unresolved"].append("invalid_circle")
    for n in node.findall(NS + "geocode"):
        result["geocodes"].append(
            {"name": text(n, "valueName", True), "value": text(n, "value", True)}
        )
    if not result["polygons"] and not result["circles"]:
        result["unresolved"].append(
            "unmapped_geocode" if result["geocodes"] else "text_only_area"
        )
    return result


def parse(data, as_of):
    root = xml(data)
    if root.tag != NS + "alert":
        raise AdvisoryError("cap_1_2_required")
    value = {
        k: text(root, k, True)
        for k in ("identifier", "sender", "sent", "status", "msgType", "scope")
    }
    if any(
        len(value[k]) > 512 or re.search(r"[\s,]", value[k])
        for k in ("identifier", "sender")
    ):
        raise AdvisoryError("invalid_cap_identity")
    value["sent"] = utc(value["sent"])
    if (
        value["status"] not in ("Actual", "Exercise", "System", "Test", "Draft")
        or value["scope"] not in ("Public", "Restricted", "Private")
        or value["msgType"] not in ("Alert", "Update", "Cancel", "Ack", "Error")
    ):
        raise AdvisoryError("invalid_cap_enum")
    value["operational"] = (
        value["status"] == "Actual"
        and value["scope"] == "Public"
        and value["msgType"] in ("Alert", "Update", "Cancel")
    )
    value["issues"] = []
    value["references"] = []
    for ref in (text(root, "references") or "").split():
        parts = ref.split(",")
        if len(parts) != 3:
            raise AdvisoryError("invalid_reference")
        value["references"].append(
            {"sender": parts[0], "identifier": parts[1], "sent": utc(parts[2])}
        )
    if len(value["references"]) > POLICY["limits"]["references"]:
        raise AdvisoryError("reference_budget")
    if value["msgType"] in ("Update", "Cancel") and not value["references"]:
        value["issues"].append("missing_update_cancel_reference")
    value["infos"] = []
    for node in root.findall(NS + "info"):
        info = {
            k: text(node, k)
            for k in (
                "language",
                "event",
                "urgency",
                "severity",
                "certainty",
                "senderName",
                "headline",
                "description",
                "instruction",
                "web",
            )
        }
        info["language"] = info["language"] or "en-US"
        info["categories"] = [
            (n.text or "").strip() for n in node.findall(NS + "category")
        ]
        info["effective"] = utc(text(node, "effective") or value["sent"])
        info["onset"] = utc(text(node, "onset")) if text(node, "onset") else None
        info["expires"] = utc(text(node, "expires")) if text(node, "expires") else None
        info["issues"] = []
        if not info["expires"] or datetime.fromisoformat(
            info["expires"].replace("Z", "+00:00")
        ) <= datetime.fromisoformat(info["effective"].replace("Z", "+00:00")):
            info["issues"].append("unknown_or_invalid_validity")
        if (
            not info["event"]
            or not info["categories"]
            or info["urgency"]
            not in ("Immediate", "Expected", "Future", "Past", "Unknown")
            or info["severity"]
            not in ("Extreme", "Severe", "Moderate", "Minor", "Unknown")
            or info["certainty"]
            not in ("Observed", "Likely", "Possible", "Unlikely", "Unknown")
        ):
            info["issues"].append("incomplete_hazard_classification")
        info["areas"] = [area(n) for n in node.findall(NS + "area")]
        if len(info["areas"]) > POLICY["limits"]["areas"]:
            raise AdvisoryError("area_budget")
        if not info["areas"]:
            info["issues"].append("missing_area")
        value["infos"].append(info)
    if len(value["infos"]) > POLICY["limits"]["infos"]:
        raise AdvisoryError("info_budget")
    if value["msgType"] in ("Alert", "Update") and not value["infos"]:
        value["issues"].append("missing_info")
    vertices = sum(
        len(ring)
        for i in value["infos"]
        for a in i["areas"]
        for p in a["polygons"]
        for ring in p["coordinates"]
    )
    geometries = sum(
        len(a["polygons"]) + len(a["circles"])
        for i in value["infos"]
        for a in i["areas"]
    )
    if vertices > POLICY["limits"]["vertices"] or geometries > 128:
        raise AdvisoryError("total_geometry_budget")
    value["identity"] = {k: value[k] for k in ("sender", "identifier", "sent")}
    return json.loads(canonical(value))


def replacement_usable(message):
    return (
        message["operational"]
        and not message["issues"]
        and message["msgType"] in ("Update", "Cancel")
        and (
            message["msgType"] == "Cancel"
            or bool(message["infos"])
            and all(
                not i["issues"] and all(not a["unresolved"] for a in i["areas"])
                for i in message["infos"]
            )
        )
    )


def lifecycle(messages):
    """Order independent, same-sender exact references. Missing/conflicting parents stay unknown."""
    identities = {}
    for m in messages:
        identities.setdefault(canonical(m["identity"]), []).append(m)
    result = {
        m["revision_id"]: {
            "state": "active"
            if m["operational"] and m["msgType"] in ("Alert", "Update")
            else "non_warning",
            "replaced_by": [],
            "issues": list(m["issues"]),
        }
        for m in messages
    }
    for group in identities.values():
        if len(group) > 1:
            for m in group:
                result[m["revision_id"]]["issues"].append("identity_conflict")
    for m in sorted(
        messages,
        key=lambda m: (
            datetime.fromisoformat(m["sent"].replace("Z", "+00:00")),
            m["revision_id"],
        ),
    ):
        if not m["operational"] or m["msgType"] not in ("Update", "Cancel"):
            continue
        for ref in m["references"]:
            targets = identities.get(canonical(ref), [])
            valid = (
                ref["sender"] == m["sender"]
                and datetime.fromisoformat(ref["sent"].replace("Z", "+00:00"))
                < datetime.fromisoformat(m["sent"].replace("Z", "+00:00"))
                and len(targets) == 1
                and len(identities[canonical(m["identity"])]) == 1
                and replacement_usable(m)
            )
            if not valid or not targets or not targets[0]["operational"]:
                result[m["revision_id"]]["issues"].append(
                    "unresolved_revision_reference"
                )
                continue
            t = result[targets[0]["revision_id"]]
            t["state"] = "cancelled" if m["msgType"] == "Cancel" else "superseded"
            t["replaced_by"].append(m["revision_id"])
    return result

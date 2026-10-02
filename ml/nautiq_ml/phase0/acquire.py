"""Bounded, allowlisted acquisition with immutable content-addressed bytes."""

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class ProbeError(ValueError):
    pass


def public_url(url, hosts):
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ProbeError("url_not_allowed")
    for result in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise ProbeError("non_public_destination")
    return parsed


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("redirect_requires_catalog_review")


class Store:
    def __init__(self, root: Path, limits: dict, offline=False):
        self.root, self.limits, self.offline = root, limits, offline
        self.downloaded = 0
        self.last_request = 0.0
        self.opener = urllib.request.build_opener(NoRedirect())
        (root / "raw").mkdir(parents=True, exist_ok=True)
        (root / "receipts").mkdir(exist_ok=True)

    def fetch(self, url, hosts):
        # Cache only this explicit request, never a changed URL or corrupt object.
        key = hashlib.sha256(url.encode()).hexdigest()
        receipt_path = self.root / "receipts" / f"{key}.json"
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if receipt.get("url") != url:
                raise ProbeError("receipt_url_mismatch")
            digest = receipt["sha256"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ProbeError("invalid_receipt")
            path = self.root / "raw" / digest
            if (
                path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest
            ):
                return path, receipt
            raise ProbeError("cache_checksum_mismatch")
        if self.offline:
            raise ProbeError("missing_offline_artifact")
        public_url(url, hosts)
        deadline = time.monotonic() + self.limits["request_deadline_seconds"]
        for attempt in range(self.limits["attempts"]):
            if time.monotonic() >= deadline:
                raise ProbeError("request_deadline")
            time.sleep(max(0, 0.2 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Nautiq-Phase0/0.1",
                    "Accept-Encoding": "identity",
                },
            )
            temp = self.root / "raw" / f".{key}.part"
            try:
                with self.opener.open(
                    request, timeout=self.limits["timeout_seconds"]
                ) as response:
                    length = response.headers.get("Content-Length")
                    if length and int(length) > self.limits["max_object_bytes"]:
                        raise ProbeError("object_too_large")
                    size, digest = 0, hashlib.sha256()
                    with temp.open("wb") as output:
                        while chunk := response.read(65536):
                            size += len(chunk)
                            self.downloaded += len(chunk)
                            if (
                                size > self.limits["max_object_bytes"]
                                or self.downloaded
                                > self.limits["max_total_download_bytes"]
                            ):
                                raise ProbeError("download_budget_exceeded")
                            if time.monotonic() >= deadline:
                                raise ProbeError("request_deadline")
                            digest.update(chunk)
                            output.write(chunk)
                    if not size or (length and size != int(length)):
                        # A truncated transport is retryable; never publish its bytes.
                        raise OSError("empty_or_truncated_object")
                    sha = digest.hexdigest()
                    destination = self.root / "raw" / sha
                    if destination.exists():
                        if hashlib.sha256(destination.read_bytes()).hexdigest() != sha:
                            raise ProbeError("existing_object_corrupt")
                        temp.unlink()
                    else:
                        temp.rename(destination)
                    receipt = {
                        "url": url,
                        "sha256": sha,
                        "bytes": size,
                        "received_at": datetime.now(timezone.utc).isoformat(),
                        "last_modified": response.headers.get("Last-Modified"),
                        "etag": response.headers.get("ETag"),
                        "content_type": response.headers.get("Content-Type"),
                    }
                    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
                    return destination, receipt
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504):
                    raise ProbeError(f"http_{error.code}") from None
                if attempt + 1 == self.limits["attempts"]:
                    raise ProbeError(f"http_{error.code}") from None
                retry = error.headers.get("Retry-After", "")
                # Long/date retry windows stop this run rather than ignoring the provider.
                if retry and (not retry.isdigit() or int(retry) > 10):
                    raise ProbeError("provider_retry_window") from None
                time.sleep(int(retry) if retry else 2**attempt)
            except (OSError, TimeoutError) as error:
                if attempt + 1 == self.limits["attempts"]:
                    raise ProbeError(type(error).__name__) from None
                time.sleep(2**attempt)
            finally:
                temp.unlink(missing_ok=True)
        raise ProbeError("request_failed")

"""Read mounted secret files without logging values or silently overriding config."""

import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

KEYS = (
    "DATABASE_URL",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
)


def load_secrets():
    for key in KEYS:
        path = os.getenv(key + "_FILE")
        if not path:
            continue
        if os.getenv(key):
            raise ValueError("conflicting_secret_configuration")
        try:
            with Path(path).open("rb") as file:
                info = os.fstat(file.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                    raise ValueError("secret_file_invalid")
                raw = file.read(16385)
            value = raw.decode("utf-8").removesuffix("\n").removesuffix("\r")
            if not value or len(raw) > 16384 or any(c in value for c in "\r\n\x00"):
                raise ValueError("secret_file_invalid")
        except (OSError, UnicodeError):
            raise ValueError("secret_file_unavailable") from None
        os.environ[key] = value
    if os.getenv("NAUTIQ_DEPLOYMENT") == "production":
        origin = urlsplit(os.getenv("PRODUCT_WEB_ORIGIN", ""))
        if (
            origin.scheme != "https"
            or not origin.netloc
            or origin.username
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError("production_https_origin_required")
        for key in ("DATABASE_URL", "MINIO_ROOT_PASSWORD"):
            value = os.getenv(key, "")
            if (
                len(value) < 24
                or "nautiq_local" in value
                or not os.getenv(key + "_FILE")
            ):
                raise ValueError("production_secret_file_required")

"""Upload a staged publish folder to S3-compatible object storage (plan 5.3 and the build steps).

Works with any S3-compatible store behind a CDN (AWS S3, Cloudflare R2,
Backblaze B2 and others), using path-style URLs and AWS Signature Version 4,
standard library only. Settings come from the environment, so no secret ever
appears on the command line or in the repository:

=============================  ==================================================
``STREETFILL_S3_ENDPOINT``      for example ``https://<account>.r2.cloudflarestorage.com``
``STREETFILL_S3_BUCKET``        bucket name
``STREETFILL_S3_REGION``        default ``us-east-1`` (R2 uses ``auto``)
``AWS_ACCESS_KEY_ID``           access key
``AWS_SECRET_ACCESS_KEY``       secret key
=============================  ==================================================

Order matters, because the app trusts the manifest:

1. Every pack the manifest lists is checked against its sha256 before anything
   is sent; a mismatch stops the upload.
2. Packs go first. They are versioned and never change, so a pack already in
   the bucket with the same size is skipped, and they are cached for a year.
3. ``manifest.json`` goes **last**, with a short cache time, so the app never
   sees a manifest that points at a pack that is not there yet.

Preview pages are for the maintainer's visual check and are not uploaded.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from .publish import load_manifest, sha256_file

PACK_CACHE = "public, max-age=31536000, immutable"
MANIFEST_CACHE = "public, max-age=300"

#: ``send(method, url, headers, body) -> (status, response headers)``
Send = Callable[[str, str, Mapping[str, str], bytes], tuple[int, Mapping[str, str]]]


@dataclass(frozen=True)
class Target:
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str
    prefix: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ, prefix: str = "") -> "Target":
        names = ["STREETFILL_S3_ENDPOINT", "STREETFILL_S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
        missing = [n for n in names if not env.get(n)]
        if missing:
            raise ValueError(f"set {', '.join(missing)} in the environment")
        return cls(
            endpoint=env["STREETFILL_S3_ENDPOINT"].rstrip("/"),
            bucket=env["STREETFILL_S3_BUCKET"],
            region=env.get("STREETFILL_S3_REGION", "us-east-1"),
            access_key=env["AWS_ACCESS_KEY_ID"],
            secret_key=env["AWS_SECRET_ACCESS_KEY"],
            prefix=prefix.strip("/"),
        )

    def url(self, key: str) -> str:
        full = f"{self.prefix}/{key}" if self.prefix else key
        return f"{self.endpoint}/{self.bucket}/{urllib.parse.quote(full)}"


# --- AWS Signature Version 4 ------------------------------------------------------

def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sign(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload_sha256: str,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    now: datetime,
    service: str = "s3",
) -> dict[str, str]:
    """Headers to send, including ``Authorization``, for a SigV4-signed request."""
    parts = urllib.parse.urlsplit(url)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    day = amz_date[:8]
    out = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    out["host"] = parts.netloc
    out["x-amz-date"] = amz_date
    out["x-amz-content-sha256"] = payload_sha256
    signed = sorted(out)
    query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}"
        for k, v in sorted(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    )
    canonical = "\n".join(
        [
            method,
            urllib.parse.quote(parts.path or "/", safe="/-_.~%"),
            query,
            "".join(f"{k}:{out[k]}\n" for k in signed),
            ";".join(signed),
            payload_sha256,
        ]
    )
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(("AWS4" + secret_key).encode(), day), region), service), "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    out["authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(signed)}, Signature={signature}"
    )
    return out


def http_send(method: str, url: str, headers: Mapping[str, str], body: bytes) -> tuple[int, Mapping[str, str]]:
    req = urllib.request.Request(url, data=body if method == "PUT" else None, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {})


# --- upload ----------------------------------------------------------------------

@dataclass
class Step:
    key: str
    path: Path
    content_type: str
    cache_control: str
    action: str = "pending"  # pending, uploaded, skipped


def plan(publish_dir: str | Path) -> list[Step]:
    """Packs first, then the manifest, after checking every pack's sha256 and size."""
    root = Path(publish_dir)
    manifest = load_manifest(root / "manifest.json")
    if not manifest["cities"]:
        raise ValueError(f"{root / 'manifest.json'} lists no cities; stage a pack first")
    steps = []
    for city in manifest["cities"]:
        path = root / city["path"]
        if not path.exists():
            raise ValueError(f"{city['id']}: {city['path']} is missing")
        if path.stat().st_size != city["bytes"] or sha256_file(path) != city["sha256"]:
            raise ValueError(f"{city['id']}: {city['path']} does not match its sha256 in the manifest")
        steps.append(Step(city["path"], path, "application/gzip", PACK_CACHE))
    steps.append(Step("manifest.json", root / "manifest.json", "application/json", MANIFEST_CACHE))
    return steps


def upload(
    publish_dir: str | Path,
    target: Target,
    *,
    send: Send = http_send,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    dry_run: bool = False,
) -> list[Step]:
    steps = plan(publish_dir)
    if dry_run:
        return steps
    for step in steps:
        url = target.url(step.key)
        creds = dict(access_key=target.access_key, secret_key=target.secret_key, region=target.region)
        if step.key != "manifest.json":
            empty = hashlib.sha256(b"").hexdigest()
            status, headers = send("HEAD", url, sign("HEAD", url, {}, empty, now=now(), **creds), b"")
            size = {k.lower(): v for k, v in headers.items()}.get("content-length")
            if status == 200 and size == str(step.path.stat().st_size):
                step.action = "skipped"  # versioned packs never change
                continue
        body = step.path.read_bytes()
        headers = {"content-type": step.content_type, "cache-control": step.cache_control,
                   "content-length": str(len(body))}
        status, _ = send("PUT", url, sign("PUT", url, headers, hashlib.sha256(body).hexdigest(), now=now(), **creds),
                         body)
        if status not in (200, 201):
            raise OSError(f"upload of {step.key} failed with HTTP {status}; the manifest was not updated"
                          if step.key != "manifest.json" else f"upload of manifest.json failed with HTTP {status}")
        step.action = "uploaded"
    return steps

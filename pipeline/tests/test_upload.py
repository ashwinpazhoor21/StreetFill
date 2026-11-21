"""Uploading a publish folder to S3-compatible storage. A fake store only; no network, no credentials."""

import hashlib
from datetime import datetime, timezone

import pytest
from test_publish import pack  # noqa: F401  (fixture)

from streetfill import upload as up
from streetfill.cli import main
from streetfill.publish import stage_pack

NOW = datetime(2013, 5, 24, tzinfo=timezone.utc)
AWS_EXAMPLE = dict(access_key="AKIAIOSFODNN7EXAMPLE", secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                   region="us-east-1", now=NOW)
ENV = {"STREETFILL_S3_ENDPOINT": "https://store.example", "STREETFILL_S3_BUCKET": "packs",
       "AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "not-a-real-secret"}


def test_signature_matches_the_aws_documented_examples():
    # "Signature Calculations for the Authorization Header", Amazon S3 API reference: GET Object and PUT Object
    get = up.sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
                  hashlib.sha256(b"").hexdigest(), **AWS_EXAMPLE)
    assert get["authorization"].endswith("Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    body = b"Welcome to Amazon S3."
    put = up.sign("PUT", "https://examplebucket.s3.amazonaws.com/test%24file.text",
                  {"Date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-storage-class": "REDUCED_REDUNDANCY"},
                  hashlib.sha256(body).hexdigest(), **AWS_EXAMPLE)
    assert "SignedHeaders=date;host;x-amz-content-sha256;x-amz-date;x-amz-storage-class" in put["authorization"]
    assert put["authorization"].endswith("Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd")


class FakeStore:
    def __init__(self, fail_on=None):
        self.objects, self.log, self.fail_on = {}, [], fail_on

    def __call__(self, method, url, headers, body):
        key = url.split("/packs/", 1)[1]
        self.log.append((method, key))
        assert headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
        if method == "HEAD":
            obj = self.objects.get(key)
            return (200, {"Content-Length": str(len(obj[0]))}) if obj else (404, {})
        if key == self.fail_on:
            return 500, {}
        assert headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
        self.objects[key] = (body, headers["cache-control"], headers["content-type"])
        return 200, {}


@pytest.fixture()
def staged(pack, tmp_path):  # noqa: F811
    out = tmp_path / "publish"
    stage_pack(pack, "test-city", out)
    stage_pack(pack, "other", out)
    return out


def target(prefix=""):
    return up.Target.from_env(ENV, prefix=prefix)


def test_packs_go_first_and_the_manifest_last(staged):
    store = FakeStore()
    steps = up.upload(staged, target(), send=store, now=lambda: NOW)
    puts = [k for m, k in store.log if m == "PUT"]
    assert puts == ["packs/other-v1.sqlite.gz", "packs/test-city-v1.sqlite.gz", "manifest.json"]
    assert [s.action for s in steps] == ["uploaded"] * 3
    assert store.objects["manifest.json"][1] == up.MANIFEST_CACHE
    assert store.objects["packs/other-v1.sqlite.gz"][1:] == (up.PACK_CACHE, "application/gzip")
    assert store.objects["packs/other-v1.sqlite.gz"][0] == (staged / "packs/other-v1.sqlite.gz").read_bytes()
    assert not any("preview" in k for _, k in store.log)  # previews stay local

    # a second run skips the packs that are already there and re-sends only the manifest
    store.log.clear()
    steps = up.upload(staged, target(), send=store, now=lambda: NOW)
    assert [s.action for s in steps] == ["skipped", "skipped", "uploaded"]
    assert [k for m, k in store.log if m == "PUT"] == ["manifest.json"]


def test_a_failed_pack_upload_never_publishes_the_manifest(staged):
    store = FakeStore(fail_on="packs/test-city-v1.sqlite.gz")
    with pytest.raises(OSError, match="manifest was not updated"):
        up.upload(staged, target(), send=store, now=lambda: NOW)
    assert "manifest.json" not in store.objects


def test_hash_mismatch_stops_before_anything_is_sent(staged):
    gz = staged / "packs" / "other-v1.sqlite.gz"
    gz.write_bytes(gz.read_bytes() + b"x")
    store = FakeStore()
    with pytest.raises(ValueError, match="does not match its sha256"):
        up.upload(staged, target(), send=store, now=lambda: NOW)
    assert store.log == []


def test_prefix_and_settings():
    t = target(prefix="/v1/")
    assert t.url("packs/a b.gz") == "https://store.example/packs/v1/packs/a%20b.gz"
    assert t.region == "us-east-1" and up.Target.from_env({**ENV, "STREETFILL_S3_REGION": "auto"}).region == "auto"
    with pytest.raises(ValueError, match="AWS_SECRET_ACCESS_KEY"):
        up.Target.from_env({k: v for k, v in ENV.items() if k != "AWS_SECRET_ACCESS_KEY"})


def test_cli_dry_run_and_upload(staged, monkeypatch, capsys):
    assert main(["upload", "--dir", str(staged), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "would upload: manifest.json"
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    store = FakeStore()
    monkeypatch.setattr(up, "http_send", store)
    assert main(["upload", "--dir", str(staged)]) == 0
    assert "uploaded: manifest.json" in capsys.readouterr().out
    monkeypatch.delenv("STREETFILL_S3_BUCKET")
    assert main(["upload", "--dir", str(staged)]) == 1
    assert "STREETFILL_S3_BUCKET" in capsys.readouterr().err

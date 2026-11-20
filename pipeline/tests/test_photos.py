"""Photos and descriptions for highlights (plan F5, 6.7). Fake Wikidata and Commons responses; no network."""

import json
import sqlite3
from pathlib import Path

import pytest
from test_highlights import doc, node
from test_matcher import GRID

from streetfill import cli, photos
from streetfill.highlights import commons_file, extract
from streetfill.pack import write_pack
from streetfill.photos import CachedFetch, licence_allowed, plain_text, resolve_photos

FIXTURE = Path(__file__).parent / "fixtures" / "mini_area.json"

ENTITIES = {
    "Q1": {"claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Oak_Street_Beach.jpg"}}}]},
           "descriptions": {"en": {"value": "beach in Chicago"}}},
    "Q2": {"claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Non free.jpg"}}}]}, "descriptions": {}},
    "Q3": {"claims": {}, "descriptions": {"en": {"value": "a sculpture"}}},
}


def file_info(title, licence, artist='<a href="//commons.wikimedia.org/wiki/User:Ann">Ann &amp; Bo</a>'):
    return {
        "title": title,
        "imageinfo": [{
            "thumburl": f"https://upload.wikimedia.org/thumb/{title[5:]}/480px.jpg",
            "url": f"https://upload.wikimedia.org/{title[5:]}",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
            "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": artist},
                            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}},
        }],
    }


FILES = {
    "File:Oak Street Beach.jpg": file_info("File:Oak Street Beach.jpg", "CC BY-SA 4.0"),
    "File:Non free.jpg": file_info("File:Non free.jpg", "CC BY-NC 2.0"),
    "File:Cloud Gate.jpg": file_info("File:Cloud Gate.jpg", "Public domain"),
    "File:No author.jpg": file_info("File:No author.jpg", "CC0", artist=""),
}


class FakeApis:
    def __init__(self):
        self.calls = []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if url == photos.WIKIDATA_API:
            return {"entities": {q: ENTITIES[q] for q in params["ids"].split("|") if q in ENTITIES}}
        pages = [FILES.get(t, {"title": t, "missing": True}) for t in params["titles"].split("|")]
        return {"query": {"pages": pages}}


def highlights():
    return extract(doc(
        node(1, 0, 0, natural="beach", name="Oak Street Beach", wikidata="Q1"),
        node(2, 300, 0, tourism="artwork", name="Gate", wikidata="Q3", wikimedia_commons="File:Cloud Gate.jpg"),
        node(3, 600, 0, tourism="museum", name="Museum", wikidata="Q2"),  # only a non-free image
        node(4, 900, 0, historic="memorial", name="Plaque", image="https://example.org/plaque.jpg"),
        node(5, 1200, 0, tourism="artwork", name="Mural", image="https://commons.wikimedia.org/wiki/File:Missing_one.jpg"),
        node(6, 1500, 0, tourism="artwork", name="Bench", wikimedia_commons="File:No author.jpg"),
    ))


def test_licence_filter_and_text():
    for ok in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "PD-US", "CC BY-SA 3.0 de", "CC BY-SA 2.5,2.0,1.0"):
        assert licence_allowed(ok), ok
    for bad in ("CC BY-NC 2.0", "CC BY-ND 4.0", "CC BY-NC-SA 3.0", "GFDL", "No restrictions", "", None):
        assert not licence_allowed(bad), bad
    assert plain_text('<a href="x">Ann &amp; Bo</a> (talk)') == "Ann & Bo (talk)"


def test_commons_file_from_tags():
    assert commons_file({"wikimedia_commons": "File:A b.jpg"}) == "File:A b.jpg"
    assert commons_file({"image": "https://commons.wikimedia.org/wiki/File:A_b%C3%A9.jpg"}) == "File:A bé.jpg"
    assert commons_file({"image": "https://upload.wikimedia.org/wikipedia/commons/a/ab/A_b.jpg"}) == "File:A b.jpg"
    thumb = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/A_b.jpg/480px-A_b.jpg"
    assert commons_file({"image": thumb}) == "File:A b.jpg"
    assert commons_file({"image": "https://example.org/x.jpg"}) is None
    assert commons_file({"wikimedia_commons": "Category:Parks"}) is None


def test_resolve_photos():
    apis = FakeApis()
    out = {h.name: h for h in resolve_photos(highlights(), apis)}
    beach = out["Oak Street Beach"]
    assert beach.photo.file == "File:Oak Street Beach.jpg"  # from Wikidata P18
    assert beach.photo.licence == "CC BY-SA 4.0" and beach.photo.author == "Ann & Bo"
    assert beach.description == "beach in Chicago"
    gate = out["Gate"]
    assert gate.photo.file == "File:Cloud Gate.jpg" and gate.description == "a sculpture"  # the tag wins
    assert out["Museum"].photo is None  # NC licence: dropped
    assert out["Plaque"].photo is None  # not on Commons: unknown licence
    assert out["Mural"].photo is None  # missing file
    assert out["Bench"].photo is None  # no author to credit
    # batched: one Wikidata call and one Commons call for all of them
    assert [u for u, _ in apis.calls] == [photos.WIKIDATA_API, photos.COMMONS_API]
    assert apis.calls[1][1]["iiurlwidth"] == "480"


def test_batches_of_fifty():
    apis = FakeApis()
    many = extract(doc(*(node(i, i * 300, 0, tourism="artwork", name=f"A{i}", wikidata=f"Q{100 + i}")
                         for i in range(120))), limit=200)
    resolve_photos(many, apis)
    assert sum(1 for u, _ in apis.calls if u == photos.WIKIDATA_API) == 3
    assert all(len(p["ids"].split("|")) <= 50 for u, p in apis.calls if u == photos.WIKIDATA_API)


def test_cache_avoids_repeat_requests(tmp_path):
    apis = FakeApis()
    cache = tmp_path / "cache.json"
    fetch = CachedFetch(apis, cache)
    resolve_photos(highlights(), fetch)
    fetch.save()
    again = CachedFetch(apis, cache)
    first = len(apis.calls)
    resolve_photos(highlights(), again)
    assert len(apis.calls) == first and again.requests == 0


def test_pack_stores_photo_and_attribution(tmp_path):
    hs = resolve_photos(highlights(), FakeApis())
    meta = write_pack(GRID, tmp_path / "p.sqlite", highlights=hs)
    assert meta["schema_version"] == "7" and meta["highlight_photo_count"] == "2"
    con = sqlite3.connect(tmp_path / "p.sqlite")
    row = con.execute("SELECT photo_url, photo_file, photo_author, photo_licence, photo_source_url, description "
                      "FROM highlights WHERE name = 'Oak Street Beach'").fetchone()
    assert row[0] is None  # not mirrored to the CDN yet
    assert row[1:4] == ("File:Oak Street Beach.jpg", "Ann & Bo", "CC BY-SA 4.0") and row[5] == "beach in Chicago"
    assert row[4].startswith("https://upload.wikimedia.org/")
    with pytest.raises(sqlite3.IntegrityError):  # a photo is never stored without credit
        con.execute("UPDATE highlights SET photo_author = NULL WHERE name = 'Oak Street Beach'")


def test_build_pack_resolve_photos(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(photos, "http_fetch_json", FakeApis())  # no network
    features = tmp_path / "f.json"
    features.write_text(json.dumps({"elements": [
        {"type": "node", "id": 1, "lat": 41.9, "lon": -87.648,
         "tags": {"natural": "beach", "name": "Oak Street Beach", "wikidata": "Q1"}},
    ]}))
    cache = tmp_path / "photos.json"
    out = tmp_path / "pack.sqlite"
    args = ["build-pack", "--osm-json", str(FIXTURE), "--out", str(out), "--osm-features", str(features),
            "--resolve-photos", "--photo-cache", str(cache)]
    monkeypatch.setattr(photos.time, "sleep", lambda s: None)  # skip the politeness pause
    assert cli.main(args) == 0
    assert "1 with a freely licensed photo (not mirrored to a CDN yet" in capsys.readouterr().out
    assert cache.exists()
    assert sqlite3.connect(out).execute("SELECT photo_licence FROM highlights").fetchone() == ("CC BY-SA 4.0",)

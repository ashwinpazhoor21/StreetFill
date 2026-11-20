"""Freely licensed photos and descriptions for highlights (plan F5 and 6.7).

For each highlight, the photo comes from the first of:

1. its ``wikimedia_commons`` tag, or an ``image`` tag that points at Commons;
2. its Wikidata item's image (property P18).

The file's licence and author are read from the Commons API (``extmetadata``).
Only public domain, CC0, CC BY and CC BY-SA files are kept; anything else
(NC, ND, GFDL-only, unknown) is dropped, and the highlight keeps its category
placeholder. The one-line description comes from the Wikidata item's English
description [Unverified: Wikidata descriptions are CC0].

What is stored: the Commons file title and page, a 480 px thumbnail URL on
Wikimedia's servers, the author, the licence and its URL. **Mirroring** the
thumbnail to StreetFill's CDN, which sets the pack's ``photo_url``, is a
separate step. It waits for the CDN and for the licence check on resizing and
mirroring CC BY-SA images (#13). Until then ``photo_url`` stays NULL, and the
app does not load images from Wikimedia directly (plan 6.7, privacy).

Requests are batched (50 titles or ids per call), identify the pipeline in
the User-Agent as Wikimedia's policy asks, and can be cached in a JSON file
so rebuilding a pack does not ask again.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from .highlights import Highlight
from .overpass import USER_AGENT

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 480
BATCH = 50

FetchJson = Callable[[str, Mapping[str, str]], dict]

_VERSIONS = r"( |-)?\d(\.\d)?(, ?\d(\.\d)?)*( [a-z]{2,3})?"  # "4.0", "2.5,2.0,1.0", "3.0 de"
_ALLOWED = re.compile(rf"^(public domain|pd(\b|-).*|cc0( 1\.0)?|cc[ -]by{_VERSIONS}|cc[ -]by-sa{_VERSIONS})$")


@dataclass(frozen=True)
class Photo:
    file: str  # "File:Name.jpg"
    page_url: str
    thumb_url: str  # on Wikimedia's servers; mirror before the app uses it
    author: str
    licence: str  # as Commons names it, for example "CC BY-SA 4.0"
    licence_url: str | None


def licence_allowed(short_name: str | None) -> bool:
    """True for public domain, CC0, CC BY and CC BY-SA (any version); False for NC, ND and the rest."""
    if not short_name:
        return False
    name = " ".join(short_name.strip().lower().split())
    return bool(_ALLOWED.match(name))


def plain_text(value: str | None) -> str:
    """Commons ``Artist`` values are HTML; keep the text."""
    text = re.sub(r"<[^>]+>", "", value or "")
    return " ".join(html.unescape(text).split())


def http_fetch_json(url: str, params: Mapping[str, str], timeout_s: float = 60) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return json.load(resp)


class CachedFetch:
    """Wraps a fetcher with a JSON file cache keyed by URL and parameters."""

    def __init__(self, fetch: FetchJson, path: str | Path | None, pause_s: float = 0.0):
        self.fetch, self.path, self.pause_s = fetch, Path(path) if path else None, pause_s
        self.cache: dict[str, dict] = {}
        if self.path and self.path.exists():
            self.cache = json.loads(self.path.read_text(encoding="utf-8"))
        self.requests = 0

    def __call__(self, url: str, params: Mapping[str, str]) -> dict:
        key = url + "?" + urllib.parse.urlencode(sorted(params.items()))
        if key not in self.cache:
            if self.requests and self.pause_s:
                time.sleep(self.pause_s)  # be gentle with the public APIs
            self.cache[key] = self.fetch(url, params)
            self.requests += 1
        return self.cache[key]

    def save(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self.cache), encoding="utf-8")


def _batches(items: Sequence[str]) -> Iterable[list[str]]:
    for i in range(0, len(items), BATCH):
        yield list(items[i : i + BATCH])


def wikidata_facts(ids: Iterable[str], fetch: FetchJson) -> dict[str, tuple[str | None, str | None]]:
    """``{Q-id: (image file title or None, English description or None)}``."""
    out: dict[str, tuple[str | None, str | None]] = {}
    unique = sorted({i for i in ids if re.fullmatch(r"Q\d+", i or "")})
    for batch in _batches(unique):
        doc = fetch(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(batch),
                                   "props": "claims|descriptions", "languages": "en"})
        for qid, ent in (doc.get("entities") or {}).items():
            image = None
            for claim in (ent.get("claims") or {}).get("P18", []):
                value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
                if isinstance(value, str) and value:
                    image = "File:" + value.replace("_", " ")
                    break
            desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value")
            out[qid] = (image, desc)
    return out


def commons_photos(files: Iterable[str], fetch: FetchJson) -> dict[str, Photo | None]:
    """``{File title: Photo, or None when missing or not freely licensed}``."""
    out: dict[str, Photo | None] = {}
    unique = sorted(set(files))
    for batch in _batches(unique):
        doc = fetch(COMMONS_API, {"action": "query", "titles": "|".join(batch), "prop": "imageinfo",
                                  "iiprop": "url|extmetadata", "iiurlwidth": str(THUMB_WIDTH)})
        query = doc.get("query") or {}
        names = {n["to"]: n["from"] for n in query.get("normalized", [])}
        for page in query.get("pages", []):
            title = names.get(page.get("title"), page.get("title"))
            info = (page.get("imageinfo") or [None])[0]
            if page.get("missing") or not info:
                out[title] = None
                continue
            meta = info.get("extmetadata") or {}

            def field(name: str) -> str | None:
                return (meta.get(name) or {}).get("value")

            licence = plain_text(field("LicenseShortName"))
            author = plain_text(field("Artist")) or plain_text(field("Credit"))
            thumb = info.get("thumburl") or info.get("url")
            if not licence_allowed(licence) or not author or not thumb:
                out[title] = None  # no usable licence or no author to credit
                continue
            out[title] = Photo(
                file=page["title"],
                page_url=info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{page['title']}",
                thumb_url=thumb,
                author=author,
                licence=licence,
                licence_url=field("LicenseUrl"),
            )
    return out


def resolve_photos(highlights: Sequence[Highlight], fetch: FetchJson) -> list[Highlight]:
    """Highlights with ``photo`` and ``description`` filled in where free sources have them."""
    facts = wikidata_facts([h.wikidata for h in highlights if h.wikidata], fetch)
    wanted: dict[str, list[str]] = {}
    for h in highlights:
        candidates = [h.commons, facts.get(h.wikidata or "", (None, None))[0]]
        wanted[h.osm_id] = [c for c in candidates if c]
    photos = commons_photos([f for files in wanted.values() for f in files], fetch)
    out = []
    for h in highlights:
        photo = next((photos[f] for f in wanted[h.osm_id] if photos.get(f)), None)
        desc = facts.get(h.wikidata or "", (None, None))[1]
        out.append(replace(h, photo=photo, description=desc))
    return out

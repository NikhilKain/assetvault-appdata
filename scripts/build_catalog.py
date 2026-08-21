"""Builds the AssetVault catalogue that ships to devices.

Run from the repo root:  `python -m scripts.build_catalog`

Output (all under `data/`, all static, all served by GitHub Pages):

    meta.json          tiny — counts and a build timestamp, for a cheap freshness check
    home.json          the home feed: hero + rails, as whole records
    type/<TYPE>.json    one file per browsable category
    index.json         the whole catalogue, for offline search

The split is the point. The phone fetches `home.json` — small, one conditional GET —
and paints immediately, then warms `index.json` in the background. Before this, the
home screen issued five parallel browses that each fanned out to seven provider APIs
and waited on the slowest of thirty-five calls.
"""

from __future__ import annotations

import datetime as dt
import os
import sys
from collections import Counter, defaultdict

from .common import (
    LK_CC0_PER_ASSET,
    LK_CC0_PROVIDER,
    Http,
    guard,
    log,
    write_json,
)
from .sources import artic, iconify, met, nasa, openverse, polyhaven, wikimedia

CATALOG_VERSION = 1

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SOURCES = [
    ("iconify", iconify.fetch),
    ("openverse", openverse.fetch),
    ("polyhaven", polyhaven.fetch),
    ("wikimedia", wikimedia.fetch),
    ("artic", artic.fetch),
    ("met", met.fetch),
    ("nasa", nasa.fetch),
]

# Mirrors AssetType.browsable in the app, in the same order.
BROWSABLE = [
    "ICON", "SVG", "ILLUSTRATION", "PHOTO", "WALLPAPER", "TEXTURE",
    "MODEL_3D", "FONT", "AUDIO", "MUSIC", "UI_KIT", "PATTERN", "MOCKUP", "VIDEO",
]

HERO_SIZE = 10
RAIL_SIZE = 18
TYPE_FEED_SIZE = 240

# Rails keep the ids and copy the app already uses, so a CDN feed and a warm live
# feed are the same page rather than two designs.
RAILS = [
    {
        "id": "icons",
        "title": "Icon sets worth knowing",
        "subtitle": "Open-source glyphs you can recolour and ship",
        "types": ["ICON", "SVG"],
        "seeAllType": "ICON",
    },
    {
        "id": "public-domain",
        "title": "Public domain",
        "subtitle": "No permission, no credit, no restrictions",
        "types": ["ILLUSTRATION", "PHOTO"],
        "publicDomainOnly": True,
        "seeAllQuery": "public domain",
    },
    {
        "id": "textures",
        "title": "Textures and 3D",
        "subtitle": "CC0 materials, HDRIs and models",
        "types": ["TEXTURE", "MODEL_3D"],
        "seeAllType": "TEXTURE",
    },
    {
        "id": "audio",
        "title": "Sound and music",
        "subtitle": "Field recordings, foley and tracks",
        "types": ["AUDIO", "MUSIC"],
        "seeAllType": "AUDIO",
    },
    {
        "id": "wallpapers",
        "title": "Wallpapers",
        "subtitle": "High-resolution backdrops, phone and desktop",
        "types": ["WALLPAPER"],
        "seeAllType": "WALLPAPER",
    },
]

HERO_TYPES = {"PHOTO", "ILLUSTRATION", "WALLPAPER"}


def likely_public_domain(record: dict) -> bool:
    """A *curation* hint for the public-domain rail — never a claim shown to a user.

    The app re-checks `license.terms.isPublicDomain` after resolving the record
    through its own registry and drops anything that does not hold up, exactly as it
    does for a live rail. So the worst a wrong guess here can do is leave a gap in a
    row; it cannot put a green badge on something that has not earned one.
    """
    kind = record.get("lk")
    if kind in (LK_CC0_PER_ASSET, LK_CC0_PROVIDER):
        return True
    code = (record.get("lc") or "").lower()
    return code in ("cc0", "pdm", "cc0-1.0", "publicdomain")


def deduplicate(records: list[dict]) -> list[dict]:
    """Same rules as AssetRepository: id first, then title+author fingerprint.

    One Flickr photo reaches us through both Openverse and Commons. Collapsing the
    pair here means the phone never spends bytes or grid space on the duplicate.
    """
    seen_ids: set[str] = set()
    seen_prints: set[str] = set()
    out: list[dict] = []

    for record in records:
        if record["i"] in seen_ids:
            continue
        seen_ids.add(record["i"])

        title = "".join(c for c in record["t"].lower() if c.isalnum())
        if len(title) >= 8:
            author = "".join(c for c in (record.get("an") or "").lower() if c.isalnum())
            fingerprint = f"{title}|{author}"
            if fingerprint in seen_prints:
                continue
            seen_prints.add(fingerprint)

        out.append(record)

    return out


def interleave(by_provider: dict[str, list[dict]]) -> list[dict]:
    """Round-robins providers so no single source owns the top of a feed."""
    out: list[dict] = []
    lists = [sorted(v, key=lambda r: -r.get("r", 0)) for v in by_provider.values()]
    for position in range(max((len(v) for v in lists), default=0)):
        for source in lists:
            if position < len(source):
                out.append(source[position])
    return out


def build_home(records: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_type[record["y"]].append(record)

    def pick(types, limit, *, public_domain_only=False, exclude=frozenset()):
        pool: dict[str, list[dict]] = defaultdict(list)
        for asset_type in types:
            for record in by_type.get(asset_type, []):
                if record["i"] in exclude:
                    continue
                if public_domain_only and not likely_public_domain(record):
                    continue
                pool[record["p"]].append(record)
        return interleave(pool)[:limit]

    hero = pick(sorted(HERO_TYPES), HERO_SIZE)
    used = {record["i"] for record in hero}

    rails = []
    for spec in RAILS:
        picked = pick(
            spec["types"],
            RAIL_SIZE,
            public_domain_only=spec.get("publicDomainOnly", False),
            exclude=used,
        )
        if not picked:
            continue
        used.update(record["i"] for record in picked)
        rails.append(
            {
                "id": spec["id"],
                "title": spec["title"],
                "subtitle": spec["subtitle"],
                "seeAllType": spec.get("seeAllType"),
                "seeAllQuery": spec.get("seeAllQuery"),
                "assets": picked,
            }
        )

    return {"hero": hero, "rails": rails}


def main() -> int:
    started = dt.datetime.now(dt.timezone.utc)
    only = set(sys.argv[1:])

    http = Http(delay=0.12)
    collected: list[dict] = []

    for name, fn in SOURCES:
        if only and name not in only:
            log(f"[{name}] skipped")
            continue
        collected.extend(guard(name, fn, http))

    if not collected:
        # Publishing an empty catalogue would replace a working one with nothing.
        # Better to fail the job and leave yesterday's file serving.
        print("no assets collected from any source — refusing to publish", file=sys.stderr)
        return 1

    records = deduplicate(collected)
    records.sort(key=lambda r: -r.get("r", 0))

    by_provider = Counter(r["p"] for r in records)
    by_type = Counter(r["y"] for r in records)

    log(f"\n{len(records)} assets after dedup (from {len(collected)})")
    for provider, count in by_provider.most_common():
        log(f"  {provider:<12} {count}")

    built_at = started.strftime("%Y-%m-%dT%H:%M:%SZ")
    header = {"version": CATALOG_VERSION, "builtAt": built_at}

    write_json(
        os.path.join(OUT, "meta.json"),
        {
            **header,
            "total": len(records),
            "providers": dict(by_provider),
            "types": dict(by_type),
        },
    )

    write_json(os.path.join(OUT, "home.json"), {**header, **build_home(records)})

    for asset_type in BROWSABLE:
        rows = [r for r in records if r["y"] == asset_type][:TYPE_FEED_SIZE]
        if rows:
            write_json(
                os.path.join(OUT, "type", f"{asset_type}.json"),
                {**header, "type": asset_type, "assets": rows},
            )

    write_json(os.path.join(OUT, "index.json"), {**header, "assets": records})

    log(f"\nbuilt in {(dt.datetime.now(dt.timezone.utc) - started).seconds}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

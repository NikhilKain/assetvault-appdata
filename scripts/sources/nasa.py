"""NASA Image Library.

NASA material is *not* a blanket public-domain release, and the app has a dedicated
licence object saying so — commercial use permitted with conditions, insignia
restricted, some items third-party copyrighted. The record carries `lk = nasa` and
the app rebuilds that exact licence, so a CDN row never reads more permissively than
the live one.
"""

from __future__ import annotations

from ..common import LK_NASA, Http, asset, clean, log

BASE = "https://images-api.nasa.gov"
PROVIDER = "nasa"

PAGE_SIZE = 60

SEEDS = [
    ("supernova", "WALLPAPER"), ("black hole", "WALLPAPER"), ("comet", "WALLPAPER"),
    ("star cluster", "WALLPAPER"), ("milky way", "WALLPAPER"), ("venus", "WALLPAPER"),
    ("mercury planet", "WALLPAPER"), ("neptune", "WALLPAPER"), ("uranus", "WALLPAPER"),
    ("pluto", "WALLPAPER"), ("asteroid", "PHOTO"), ("rover", "PHOTO"),
    ("satellite", "PHOTO"), ("rocket engine", "PHOTO"), ("spacewalk", "PHOTO"),
    ("nebula", "WALLPAPER"), ("galaxy", "WALLPAPER"), ("earth from space", "WALLPAPER"),
    ("mars surface", "PHOTO"), ("apollo", "PHOTO"), ("launch", "PHOTO"),
    ("astronaut", "PHOTO"), ("saturn", "WALLPAPER"), ("jupiter", "WALLPAPER"),
    ("hubble", "WALLPAPER"), ("james webb", "WALLPAPER"), ("aurora", "PHOTO"),
    ("space station", "PHOTO"), ("solar flare", "PHOTO"), ("moon", "WALLPAPER"),
    ("spacecraft illustration", "ILLUSTRATION"), ("mission patch", "ILLUSTRATION"),
]


def fetch(http: Http) -> list[dict]:
    out: list[dict] = []

    for seed, asset_type in SEEDS:
        try:
            data = http.get_json(
                f"{BASE}/search",
                {"q": seed, "media_type": "image", "page": 1, "page_size": PAGE_SIZE},
            )
        except Exception as e:  # noqa: BLE001
            log(f"  [nasa] '{seed}': {e}")
            continue

        items = ((data.get("collection") or {}).get("items")) or []
        got = 0
        for position, item in enumerate(items):
            payload = (item.get("data") or [{}])[0]
            nasa_id = payload.get("nasa_id")
            title = clean(payload.get("title"))
            if not nasa_id or not title:
                continue

            preview = next(
                (l.get("href") for l in (item.get("links") or []) if l.get("rel") == "preview"),
                None,
            )
            creator = (
                clean(payload.get("photographer"))
                or clean(payload.get("secondary_creator"))
                or clean(payload.get("center"))
            )

            record = asset(
                provider=PROVIDER,
                provider_asset_id=nasa_id,
                title=title,
                type=asset_type,
                thumbnail=preview,
                preview=preview,
                source_url=f"https://images.nasa.gov/details/{nasa_id}",
                file_format="JPG",
                author=creator,
                lk=LK_NASA,
                tags=payload.get("keywords") or [],
                description=clean(payload.get("description")),
                attribution=f"{title} — courtesy NASA{f' / {creator}' if creator else ''}",
                rank=max(0.0, PAGE_SIZE - position),
            )
            if record:
                out.append(record)
                got += 1

        log(f"  [nasa] '{seed}': {got}")

    return out
